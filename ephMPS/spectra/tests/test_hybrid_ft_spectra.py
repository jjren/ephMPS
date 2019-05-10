# -*- coding: utf-8 -*-
# Author: Jiajun Ren <jiajunren0522@gmail.com>

import os

import numpy as np
import pytest

from ephMPS.mps import Mpo, MpDm
from ephMPS.spectra import SpectraFiniteT
from ephMPS.spectra.tests import cur_dir
from ephMPS.utils import Quantity
from ephMPS.tests import parameter


@pytest.mark.parametrize(
    "mol_list, etot_std, occ_std",
    (
        [
            parameter.hybrid_mol_list,
            0.0853441664951,
            [0.20881609, 0.35239430, 0.43878960],
        ],
        [parameter.mol_list, 0.0853413581416, [0.20881782, 0.35239674, 0.43878545]],
    ),
)
def test_thermal_prop(mol_list, etot_std, occ_std):
    nsteps = 100

    mps = MpDm.max_entangled_ex(mol_list)
    mpo = Mpo(mol_list)
    beta = Quantity(298, "K").to_beta() / 2
    mps = mps.thermal_prop(mpo, nsteps, beta, inplace=True)
    MPO, HAM, Etot, A_el = mps.construct_hybrid_Ham(mpo, debug=True)

    assert np.allclose(Etot, etot_std, rtol=1e-3)
    assert np.allclose(A_el, occ_std, rtol=1e-3)


@pytest.mark.parametrize(
    "mol_list, spectratype, std_fname",
    (
        [parameter.mol_list, "abs", "hybrid_FT_abs_pure.npy"],
        [parameter.hybrid_mol_list, "abs", "hybrid_FT_abs_hybrid.npy"],
        [parameter.mol_list, "emi", "hybrid_FT_emi_pure.npy"],
        [parameter.hybrid_mol_list, "emi", "hybrid_FT_emi_hybrid.npy"],
    ),
)
def Test_FT_hybrid_TDDMRG_TDH(mol_list, spectratype, std_fname):
    temperature = Quantity(298, "K")
    insteps = 50
    finite_t = SpectraFiniteT(
        mol_list, spectratype, temperature, insteps, Quantity(2.28614053, "ev")
    )
    finite_t.info_interval = 50
    dt = 30.0
    nsteps = 300
    finite_t.evolve(dt, nsteps)
    with open(os.path.join(cur_dir, std_fname), "rb") as fin:
        std = np.load(fin)
    assert np.allclose(finite_t.autocorr[:nsteps], std[:nsteps], rtol=1e-2)


# from matplotlib import pyplot as plt
# plt.plot(finite_t.autocorr)
# plt.plot(std)
# plt.show()