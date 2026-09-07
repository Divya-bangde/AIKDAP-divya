"""Generic binary/multiclass scoring helpers, shared by both tracks.

No project-specific knowledge lives here -- just confusion-matrix
arithmetic, so the two tracks (and any future one) report metrics the
same way.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class BinaryConfusion:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def fpr(self) -> float:
        return self.fp / (self.fp + self.tn) if (self.fp + self.tn) else 0.0

    def as_dict(self) -> dict:
        return {
            "tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "fpr": round(self.fpr, 4),
        }


def binary_confusion(pairs: list[tuple[bool, bool]]) -> BinaryConfusion:
    """`pairs` is `(predicted, actual)`."""
    c = BinaryConfusion()
    for predicted, actual in pairs:
        if predicted and actual:
            c.tp += 1
        elif predicted and not actual:
            c.fp += 1
        elif not predicted and actual:
            c.fn += 1
        else:
            c.tn += 1
    return c


@dataclass
class MulticlassReport:
    labels: list[str]
    matrix: dict[str, Counter] = field(default_factory=dict)  # actual -> Counter(predicted)
    total: int = 0
    correct: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def per_class(self) -> dict[str, dict]:
        """Precision/recall/F1 for each label, one-vs-rest."""
        out: dict[str, dict] = {}
        for label in self.labels:
            tp = self.matrix.get(label, Counter()).get(label, 0)
            fn = sum(
                count for actual, preds in self.matrix.items()
                for predicted, count in preds.items()
                if actual == label and predicted != label
            )
            fp = sum(
                count for actual, preds in self.matrix.items()
                for predicted, count in preds.items()
                if predicted == label and actual != label
            )
            precision = tp / (tp + fp) if (tp + fp) else 1.0
            recall = tp / (tp + fn) if (tp + fn) else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
            out[label] = {
                "tp": tp, "fp": fp, "fn": fn,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
            }
        return out

    def confusion_matrix(self) -> dict[str, dict[str, int]]:
        return {
            actual: dict(preds)
            for actual, preds in self.matrix.items()
        }


def multiclass_report(pairs: list[tuple[str, str]], labels: list[str]) -> MulticlassReport:
    """`pairs` is `(predicted, actual)`."""
    report = MulticlassReport(labels=labels)
    for predicted, actual in pairs:
        report.matrix.setdefault(actual, Counter())[predicted] += 1
        report.total += 1
        if predicted == actual:
            report.correct += 1
    return report
