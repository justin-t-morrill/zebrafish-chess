"""Export best-checkpoint validation move distributions, with dataset row IDs."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch
from train import MoveCNN, load_dataset


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset", type=Path)
    p.add_argument("runs", type=Path)
    a = p.parse_args()
    torch.set_num_threads(6)
    data, groups, manifest = load_dataset(a.dataset)
    idx = np.flatnonzero(data["split"] == 1)
    for mode in ("position", "move", "engine", "scalar"):
        root = a.runs / mode
        output = root / "validation_move_distributions.npz"
        if output.exists():
            raise ValueError(f"Already exported: {output}")
        # Only this experiment's locally generated checkpoint is accepted here.
        with torch.serialization.safe_globals([torch.torch_version.TorchVersion]):
            checkpoint = torch.load(root / "best.pt", map_location="cpu", weights_only=True)
        assert checkpoint["config"]["source_sha256"] == manifest["source_sha256"]
        model = MoveCNN(mode, data["engine"].shape[1]).cuda().eval()
        model.load_state_dict(checkpoint["state_dict"])
        outputs = []
        with torch.no_grad():
            for start in range(0, len(idx), 512):
                selected = idx[start:start+512]
                batch = [torch.as_tensor(data[k][selected], device="cuda") for k in ("board", "state", "move", "engine")]
                outputs.append(model(*batch).softmax(1).cpu().numpy())
        probabilities = np.concatenate(outputs)
        assert np.isfinite(probabilities).all() and np.allclose(probabilities.sum(1), 1, atol=1e-5)
        np.savez_compressed(output, row=idx, group=data["group"][idx], probabilities=probabilities)
        print(json.dumps({"mode": mode, "moves_exported": len(idx), "file": str(output)}), flush=True)


if __name__ == "__main__":
    main()
