from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from mts_utils import DualReferenceMTS, prepare_feature_matrix


def main():
    rng = np.random.default_rng(42)
    features = ["f1", "f2", "f3", "f4", "f5"]
    healthy = pd.DataFrame(rng.normal(0, 1, size=(100, len(features))), columns=features)
    tjs = pd.DataFrame(rng.normal(1.5, 1, size=(8, len(features))), columns=features)
    test = pd.concat([
        healthy.assign(sample_group="healthy"),
        tjs.assign(sample_group="tjs"),
    ], ignore_index=True)
    X = prepare_feature_matrix(test, features)
    mts = DualReferenceMTS(covariance="oas").fit(X[test.sample_group == "healthy"], X[test.sample_group == "tjs"])
    scores = mts.score(X)
    print(scores.groupby(test.sample_group)["risk_tjs"].mean())
    assert scores.loc[test.sample_group == "tjs", "risk_tjs"].mean() > scores.loc[test.sample_group == "healthy", "risk_tjs"].mean()
    print("Synthetic smoke test passed.")


if __name__ == "__main__":
    main()
