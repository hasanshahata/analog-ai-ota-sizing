"""Torch models for amortized inverse design (Phase 5 PoC).

`ProposalNet` outputs K candidate designs per request through sigmoid units
affine-mapped onto [0, 1]; `data.denormalize_designs` maps that exactly onto
`config.DESIGN_BOUNDS`, so a proposal can never violate the geometry /
gm-Id / current domain. Multimodality (one request, many valid designs) is
handled by K heads trained with a best-of-K loss: each request supervises
only its closest head, letting heads specialize on different design styles.
"""

from __future__ import annotations

import torch
from torch import nn


class ProposalNet(nn.Module):
    def __init__(self, k_heads: int = 5, hidden: tuple = (256, 256),
                 in_dim: int = 4, out_dim: int = 5):
        super().__init__()
        self.k_heads = k_heads
        self.out_dim = out_dim
        layers: list[nn.Module] = []
        prev = in_dim
        for h in hidden:
            layers += [nn.Linear(prev, h), nn.ReLU()]
            prev = h
        self.trunk = nn.Sequential(*layers)
        self.head = nn.Linear(prev, k_heads * out_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """[B, in] -> [B, K, out] in [0, 1] (unit design space)."""
        z = self.trunk(x)
        u = torch.sigmoid(self.head(z))
        return u.view(-1, self.k_heads, self.out_dim)


def best_of_k_loss(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """MSE of the closest head per request: pred [B, K, D], target [B, D]."""
    per_head = ((pred - target.unsqueeze(1)) ** 2).mean(dim=2)  # [B, K]
    return per_head.min(dim=1).values.mean()


class RiskNet(nn.Module):
    """OOD/risk head: positive = request looks achievable, negative = the
    dataset carries evidence against it (label schema v2 — evidence, not
    proof of infeasibility)."""

    def __init__(self, hidden: tuple = (256, 256), in_dim: int = 4):
        super().__init__()
        layers: list[nn.Module] = []
        prev = in_dim
        for h in hidden:
            layers += [nn.Linear(prev, h), nn.ReLU()]
            prev = h
        layers.append(nn.Linear(prev, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
