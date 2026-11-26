"""Frozen-input RatingNet inference shared by validation and the review bridge."""
import math
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


class RatingNet(nn.Module):
    def __init__(self):
        super().__init__()
        blocks = []
        for index, (source, target) in enumerate(zip([12, 32, 64, 128], [32, 64, 128, 256])):
            blocks += [nn.Conv2d(source, target, 3, padding=1), nn.BatchNorm2d(target), nn.LeakyReLU()]
            if index < 3:
                blocks.append(nn.AvgPool2d(2))
        self.cnn = nn.Sequential(*blocks)
        self.dropout = nn.Dropout(.5)
        self.rnn = nn.LSTM(260, 64, 3, batch_first=True, bidirectional=True, dropout=0)
        self.head = nn.Sequential(nn.Linear(128, 32), nn.LeakyReLU(), nn.Dropout(.5), nn.Linear(32, 2))

    def forward(self, pieces, auxiliary, lengths):
        b, t = pieces.shape[:2]
        planes = F.one_hot(pieces.long(), 13)[..., 1:].float()
        planes = planes.view(b, t, 8, 8, 12).permute(0, 1, 4, 2, 3).flip(-2)
        features = self.dropout(self.cnn(planes.flatten(0, 1)).flatten(1)).view(b, t, -1)
        sequence, _ = self.rnn(torch.cat((features, auxiliary), -1))
        output = self.head(sequence)
        return output[torch.arange(b, device=pieces.device), lengths - 1]


def auxiliary(clocks, controls):
    missing = ~np.isfinite(clocks)
    shape = clocks.shape
    base = np.log1p(controls[:, :1]) / math.log(3601)
    inc = np.log1p(controls[:, 1:2]) / math.log(61)
    return np.stack([np.where(missing, 0, (clocks-273)/380), missing.astype(np.float32),
                     np.broadcast_to(base, shape), np.broadcast_to(inc, shape)], -1).astype(np.float32)


def load_checkpoint(path, device="cpu"):
    # Only project-owned model files are loaded; never load a user PGN as weights.
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    model = RatingNet().to(device).eval()
    model.load_state_dict(checkpoint.get("model", checkpoint.get("state_dict")))
    return model, float(checkpoint["rating_mean"]), float(checkpoint["rating_std"])


@torch.inference_mode()
def infer(model, mean, std, positions, clocks, controls, lengths, device="cpu", batch_size=128):
    aux = auxiliary(clocks, controls)
    result = []
    for start in range(0, len(positions), batch_size):
        sl = slice(start, start+batch_size)
        values = model(torch.as_tensor(positions[sl], device=device),
                       torch.as_tensor(aux[sl], device=device),
                       torch.as_tensor(lengths[sl].astype(np.int64), device=device))
        result.append(values.cpu().numpy() * std + mean)
    return np.concatenate(result)
