# -*- coding: utf-8 -*-
# Author: Jiajun Ren <jiajunren0522@gmail.com>

"""
    some energy units converter
"""

import scipy.constants

# 1 a.u. = au2ev eV
au2ev = scipy.constants.physical_constants["Hartree energy in eV"][0]

# 1 cm^-1 = cm2au a.u.
cm2au = (
    1.0e2
    * scipy.constants.physical_constants["inverse meter-hertz relationship"][0]
    / scipy.constants.physical_constants["hartree-hertz relationship"][0]
)

# 1 cm^-1 = cm2ev eV
cm2ev = cm2au * au2ev

# 1 fs = fs2au a.u
fs2au = 1.0e-15 / scipy.constants.physical_constants["atomic unit of time"][0]
K2au = scipy.constants.physical_constants["kelvin-hartree relationship"][0]
au2K = scipy.constants.physical_constants["hartree-kelvin relationship"][0]

# nm to au
def nm2au(l):
    return 1.0e7 / l * cm2au


def au2nm(e):
    return 1.0e7 / (e / cm2au)