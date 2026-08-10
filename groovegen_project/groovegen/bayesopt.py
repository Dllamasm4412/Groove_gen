"""
GrooveGen Step 6 — Bayesian Optimization scaffold over the knob space.

Goal (per the project's scientific framing):
  - Find each PARTICIPANT'S groove "sweet spot" in the 5-knob space, sample-efficiently.
  - As a byproduct, recover a LEARNED SENSITIVITY RANKING ("which knobs matter")
    from the fitted GP — this is the actual contribution, not stimulus generation.

Design choices (deliberate, defended in the project notes):
  - Surrogate = Gaussian Process (sklearn GaussianProcessRegressor), NOT a deep net.
    At pilot N (~20-40 trials/person) a GP with a Matern-5/2 kernel is the correct,
    well-calibrated, sample-efficient choice. DL stays OFF the stimulus-production /
    search side during the causal experiment.
  - ARD (one lengthscale per knob) so the kernel itself encodes per-knob relevance.
    Short lengthscale  -> output varies fast along that knob -> knob MATTERS.
    Long lengthscale   -> output ~flat along that knob       -> knob is inert.
  - WhiteKernel models rating noise (human groove ratings are noisy / repeat-inconsistent).
  - Acquisition = Expected Improvement (EI). Sample-efficient default for <=~40 evals.
  - Search space is the SAME continuous knob ranges the generator already accepts, so an
    optimizer suggestion can be handed straight to groovegen.GrooveParams and rendered.

This module is generator-agnostic: you provide an `objective(params_dict) -> float`
(higher = groovier). For human-in-the-loop pilots, use the ask()/tell() API:
    opt = GrooveBO(seed=0)
    for t in range(N):
        x = opt.ask()                  # dict of knob values to render & rate
        # ...render with groovegen, collect rating y in [0,1] (or a z-scored PPG metric)...
        opt.tell(x, y)
    report = opt.sensitivity_report()  # learned "which knobs matter"
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Callable, Optional

from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern, ConstantKernel, WhiteKernel
from scipy.stats import norm


# ----------------------------------------------------------------------------
# Knob search space. Bounds mirror groove_knob_literature.md sweep extents so a
# suggested point is always renderable by groovegen.generate().
# (name, low, high, is_integer)
# ----------------------------------------------------------------------------
KNOB_SPACE = [
    ("tempo_bpm",              60.0, 160.0, True),
    ("event_density",           4.0,  24.0, True),
    ("swing_amount",            1.0,   2.0, False),
    ("syncopation_level",       0.0,   1.0, False),
    ("microtiming_variance_ms", 0.0,  35.0, False),
]
KNOB_NAMES = [k[0] for k in KNOB_SPACE]
LOWS  = np.array([k[1] for k in KNOB_SPACE], dtype=float)
HIGHS = np.array([k[2] for k in KNOB_SPACE], dtype=float)
IS_INT = np.array([k[3] for k in KNOB_SPACE], dtype=bool)
DIM = len(KNOB_SPACE)


def _to_unit(x_phys: np.ndarray) -> np.ndarray:
    """Physical knob values -> [0,1]^D (GP works in normalized space)."""
    return (np.asarray(x_phys, float) - LOWS) / (HIGHS - LOWS)


def _to_phys(x_unit: np.ndarray) -> np.ndarray:
    """[0,1]^D -> physical knob values, rounding integer knobs."""
    x = np.clip(np.asarray(x_unit, float), 0.0, 1.0)
    phys = LOWS + x * (HIGHS - LOWS)
    phys = np.where(IS_INT, np.round(phys), phys)
    return phys


def _dict_from_phys(x_phys: np.ndarray) -> dict:
    d = {}
    for i, name in enumerate(KNOB_NAMES):
        v = x_phys[i]
        d[name] = int(v) if IS_INT[i] else float(v)
    return d


@dataclass
class GrooveBO:
    """Per-participant Bayesian optimizer over the 5-knob groove space."""
    seed: int = 0
    n_init: int = 6                  # space-filling (Sobol-ish LHS) seed points
    maximize: bool = True            # higher groove = better
    xi: float = 0.01                 # EI exploration margin
    n_restarts: int = 8              # acquisition optimizer multistarts
    rng: np.random.Generator = field(init=False)
    X_unit: list = field(default_factory=list, init=False)   # observed points (unit cube)
    y: list = field(default_factory=list, init=False)        # observed objective
    gp: Optional[GaussianProcessRegressor] = field(default=None, init=False)
    _init_queue: list = field(default_factory=list, init=False)

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)
        self._init_queue = list(self._latin_hypercube(self.n_init))

    # ---- space-filling seed design --------------------------------------
    def _latin_hypercube(self, n: int) -> np.ndarray:
        """Simple seeded LHS in the unit cube for initial exploration."""
        cut = np.linspace(0, 1, n + 1)
        u = self.rng.uniform(size=(n, DIM))
        pts = cut[:n, None] + u * (1.0 / n)
        for j in range(DIM):
            self.rng.shuffle(pts[:, j])
        return pts

    # ---- GP fit ----------------------------------------------------------
    def _fit_gp(self):
        X = np.array(self.X_unit)
        y = np.array(self.y, float)
        y_signed = y if self.maximize else -y
        # ARD Matern-5/2 + constant scale + observation noise.
        kernel = (
            ConstantKernel(1.0, (1e-2, 1e2))
            * Matern(length_scale=np.ones(DIM), length_scale_bounds=(1e-2, 1e2), nu=2.5)
            + WhiteKernel(noise_level=0.1, noise_level_bounds=(1e-4, 1e0))
        )
        self.gp = GaussianProcessRegressor(
            kernel=kernel,
            normalize_y=True,
            n_restarts_optimizer=5,
            random_state=self.seed,
        )
        self.gp.fit(X, y_signed)

    # ---- acquisition: Expected Improvement ------------------------------
    def _ei(self, Xq_unit: np.ndarray) -> np.ndarray:
        mu, sd = self.gp.predict(Xq_unit, return_std=True)
        sd = np.maximum(sd, 1e-9)
        y_best = np.max(self.gp.y_train_ if hasattr(self.gp, "y_train_") else self.y)
        # use observed best in signed space
        y_signed = np.array(self.y, float)
        y_signed = y_signed if self.maximize else -y_signed
        f_best = np.max(y_signed)
        imp = mu - f_best - self.xi
        z = imp / sd
        return imp * norm.cdf(z) + sd * norm.pdf(z)

    def _maximize_ei(self) -> np.ndarray:
        # random candidate pool + local polish via best-of-restarts
        pool = self.rng.uniform(size=(2000, DIM))
        ei = self._ei(pool)
        order = np.argsort(ei)[::-1][: self.n_restarts]
        best_x, best_v = pool[order[0]], ei[order[0]]
        # coordinate jitter polish around top candidates
        for idx in order:
            x = pool[idx].copy()
            for _ in range(40):
                cand = np.clip(x + self.rng.normal(0, 0.03, DIM), 0, 1)
                v = self._ei(cand[None, :])[0]
                if v > best_v:
                    best_v, best_x, x = v, cand, cand
        return best_x

    # ---- public ask/tell -------------------------------------------------
    def ask(self) -> dict:
        """Return the next knob setting to render & rate (physical units)."""
        if self._init_queue:
            x_unit = self._init_queue.pop(0)
        else:
            self._fit_gp()
            x_unit = self._maximize_ei()
        self._pending = x_unit
        return _dict_from_phys(_to_phys(x_unit))

    def tell(self, params: dict, y: float):
        """Register an observed objective value for a rendered/rated stimulus."""
        # accept either the dict we returned or any physical-unit dict
        x_phys = np.array([params[n] for n in KNOB_NAMES], float)
        self.X_unit.append(_to_unit(x_phys).tolist())
        self.y.append(float(y))

    # ---- best so far -----------------------------------------------------
    def best(self) -> tuple[dict, float]:
        y = np.array(self.y, float)
        i = int(np.argmax(y)) if self.maximize else int(np.argmin(y))
        return _dict_from_phys(_to_phys(np.array(self.X_unit[i]))), float(y[i])

    # ---- sensitivity readout: "which knobs matter" ----------------------
    def sensitivity_report(self) -> dict:
        """
        Two complementary, defensible relevance measures from the fitted GP:
          (1) ARD inverse-lengthscale: shorter lengthscale -> knob matters more.
          (2) Posterior-mean range along each axis (others held at the current
              best), a model-agnostic 'main-effect amplitude'.
        Returns a dict with per-knob scores + a ranking. Requires a fitted GP
        (>= n_init observations).
        """
        if self.gp is None:
            self._fit_gp()
        # (1) ARD lengthscales
        ls = None
        for hp in self.gp.kernel_.get_params().values():
            if isinstance(hp, np.ndarray) and hp.shape == (DIM,):
                ls = hp
                break
        if ls is None:  # fallback: parse from kernel theta
            ls = np.exp(self.gp.kernel_.theta[1:1 + DIM])
        inv_ls = 1.0 / np.asarray(ls, float)
        inv_ls_norm = inv_ls / inv_ls.sum()

        # (2) main-effect amplitude: sweep each axis over [0,1], others at best
        x_best_unit = np.array(self.X_unit[int(np.argmax(self.y))], float)
        grid = np.linspace(0, 1, 25)
        amp = np.zeros(DIM)
        for j in range(DIM):
            XX = np.tile(x_best_unit, (grid.size, 1))
            XX[:, j] = grid
            mu, _ = self.gp.predict(XX, return_std=True)
            amp[j] = mu.max() - mu.min()
        amp_norm = amp / amp.sum() if amp.sum() > 0 else amp

        combined = 0.5 * inv_ls_norm + 0.5 * amp_norm
        rank = np.argsort(combined)[::-1]
        return {
            "knob_names": KNOB_NAMES,
            "ard_lengthscale": dict(zip(KNOB_NAMES, np.round(ls, 4).tolist())),
            "ard_relevance_norm": dict(zip(KNOB_NAMES, np.round(inv_ls_norm, 4).tolist())),
            "maineffect_amplitude_norm": dict(zip(KNOB_NAMES, np.round(amp_norm, 4).tolist())),
            "combined_relevance": dict(zip(KNOB_NAMES, np.round(combined, 4).tolist())),
            "ranking_high_to_low": [KNOB_NAMES[i] for i in rank],
        }


# ----------------------------------------------------------------------------
# Closed-loop driver for an automated objective (e.g., a synthetic groove proxy
# or, later, a Track-C PPG/GSR decoder estimate). Human pilots use ask/tell.
# ----------------------------------------------------------------------------
def run_bo(objective: Callable[[dict], float],
           n_trials: int = 30,
           seed: int = 0,
           maximize: bool = True,
           verbose: bool = True) -> GrooveBO:
    opt = GrooveBO(seed=seed, maximize=maximize)
    for t in range(n_trials):
        x = opt.ask()
        y = float(objective(x))
        opt.tell(x, y)
        if verbose:
            bx, by = opt.best()
            print(f"trial {t:02d}  y={y:+.3f}  best={by:+.3f}  x={ {k: round(v,2) for k,v in x.items()} }")
    return opt
