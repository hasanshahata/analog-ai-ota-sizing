# Archive — frozen history. Do not import from here.

| Directory | Contents | Notes |
|---|---|---|
| `versions/V2_Trainer … V12_Trainer/` | The twelve self-contained trainer trees actually used for the Kaggle runs (env code, notebooks, kernel metadata, dataset zips) | Preserved verbatim; each was imported only by its own `Test_Scripts/test_vN_model.py` via `sys.path` injection — the pattern the canonical package replaces |
| `versions/V7…V12_Trainer/ppo_ota_tensorboard/` | One TensorBoard event file per version | V7–V12 files are byte-identical (md5 `d4e7a0df…`): they are six copies of a single run, so they do not evidence per-version training. Unique V2/V3 events remain in their trees; two additional unique files are in `models/training_telemetry/` |
| `versions/*/tech_luts/*.pkl` | Deleted | All were 0-byte placeholders (Kaggle pulled the real LUTs from kernel outputs) |
| `legacy_root/` | The original 7-parameter root package (`core/`, `optimizer/`, `circuits/`, `utils/`), the FastAPI `web_app/` serving the V1 model, `analog_ai_solver.py`, `diagnostic_sweep.py`, `generate_results_table.py`, `Test_Scripts/`, and the sample netlist | Incompatible with every V2–V12 model; kept for reference. The web API returned unconditional `success` and never accepted CL as an input |
| `kaggle/` | Notebook builders (`build_vN_notebook.py`), Colab/Kaggle notebooks, `zip_for_kaggle.py`, run scripts | How training was packaged for Kaggle |

Nothing under `archive/` is on any import path of the canonical package.
Recovery: the full pre-reorganization state is git commit `912811d`.
