"""Training loops for the Phase 5 proof of concept (CPU, minutes per seed).

Checkpoint selection is two-stage by design: early stopping uses the
validation best-of-K loss (cheap, no oracle), and the final champion among
seeds is selected by LUT-verified pass rate on a validation subsample
(`evaluate.select_champion`) — training loss never selects anything.
"""

from __future__ import annotations

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from .model import ProposalNet, RiskNet, best_of_k_loss


def _mk_loader(x, d, batch: int, shuffle: bool, generator=None):
    return DataLoader(TensorDataset(torch.as_tensor(x),
                                    torch.as_tensor(d)),
                      batch_size=batch, shuffle=shuffle, generator=generator)


def train_proposal(x_tr, d_tr, x_va, d_va, seed: int = 0, k_heads: int = 5,
                   hidden: tuple = (256, 256), epochs: int = 300,
                   batch: int = 512, lr: float = 1e-3,
                   weight_decay: float = 1e-5, patience: int = 30,
                   device: str = "cpu") -> tuple[ProposalNet, dict]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = ProposalNet(k_heads=k_heads, hidden=hidden).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr,
                           weight_decay=weight_decay)
    gen = torch.Generator().manual_seed(seed)
    tr = _mk_loader(x_tr, d_tr, batch, True, gen)
    x_va_t = torch.as_tensor(x_va, device=device)
    d_va_t = torch.as_tensor(d_va, device=device)

    history = {"train": [], "val": []}
    best_val, best_state, bad = float("inf"), None, 0
    for epoch in range(epochs):
        model.train()
        run = 0.0
        for xb, db in tr:
            opt.zero_grad()
            loss = best_of_k_loss(model(xb), db)
            loss.backward()
            opt.step()
            run += float(loss.detach()) * len(xb)
        history["train"].append(run / len(x_tr))

        model.eval()
        with torch.no_grad():
            val = float(best_of_k_loss(model(x_va_t), d_va_t))
        history["val"].append(val)
        if val < best_val - 1e-6:
            best_val, bad = val, 0
            best_state = {k: v.detach().clone()
                          for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    history["best_val"] = best_val
    history["epochs_run"] = len(history["val"])
    return model, history


def train_risk(x_tr, y_tr, x_va, y_va, seed: int = 0,
               hidden: tuple = (256, 256), epochs: int = 200,
               batch: int = 512, lr: float = 1e-3, patience: int = 25,
               device: str = "cpu") -> tuple[RiskNet, dict]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = RiskNet(hidden=hidden).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    bce = nn_BCE()
    gen = torch.Generator().manual_seed(seed)
    tr = DataLoader(TensorDataset(torch.as_tensor(x_tr),
                                  torch.as_tensor(y_tr)),
                    batch_size=batch, shuffle=True, generator=gen)
    x_va_t = torch.as_tensor(x_va, device=device)
    y_va_t = torch.as_tensor(y_va, device=device)

    history = {"train": [], "val": []}
    best_val, best_state, bad = float("inf"), None, 0
    for epoch in range(epochs):
        model.train()
        run = 0.0
        for xb, yb in tr:
            opt.zero_grad()
            loss = bce(model(xb), yb)
            loss.backward()
            opt.step()
            run += float(loss.detach()) * len(xb)
        history["train"].append(run / max(len(x_tr), 1))
        model.eval()
        with torch.no_grad():
            val = float(bce(model(x_va_t), y_va_t))
        history["val"].append(val)
        if val < best_val - 1e-6:
            best_val, bad = val, 0
            best_state = {k: v.detach().clone()
                          for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    history["best_val"] = best_val
    return model, history


def nn_BCE():
    return torch.nn.BCEWithLogitsLoss()


def save_checkpoint(path: str, proposal: ProposalNet, risk: RiskNet | None,
                    meta: dict) -> None:
    torch.save({
        "proposal_state": proposal.state_dict(),
        "risk_state": risk.state_dict() if risk is not None else None,
        "meta": meta,   # k_heads, hidden, seed, feature ranges, dataset
                        # manifest sha, epochs — everything reproduction needs
    }, path)


def load_checkpoint(path: str, device: str = "cpu",
                    expected_tail_device: str = "ideal") -> dict:
    ck = torch.load(path, map_location=device, weights_only=False)
    checkpoint_mode = ck.get("meta", {}).get("tail_device", "ideal")
    if expected_tail_device != "ideal" or checkpoint_mode != "ideal":
        raise ValueError(
            "current checkpoints are five-output ideal-tail models; "
            f"checkpoint={checkpoint_mode!r}, engine={expected_tail_device!r}")
    proposal = ProposalNet(k_heads=ck["meta"]["k_heads"],
                           hidden=tuple(ck["meta"]["hidden"]))
    proposal.load_state_dict(ck["proposal_state"])
    proposal.eval()
    risk = None
    if ck["risk_state"] is not None:
        risk = RiskNet(hidden=tuple(ck["meta"]["hidden"]))
        risk.load_state_dict(ck["risk_state"])
        risk.eval()
    return {"proposal": proposal, "risk": risk, "meta": ck["meta"]}
