# -*- coding: utf-8 -*-
# Author: Jiajun Ren <jiajunren0522@gmail.com>

'''
functions wiht QNargs can return two different MPO/MPS objects
for QNargs=None: MPO/MPS objects are pure MPO/MPS matrices list
for QNargs!=None: MPO/MPS objects are lists of[MPO/MPS matrices, MPO/MPS QuantumNumber
    list, QuantumNumber L/R boundary side index, conserved total QuantumNumber]
'''

import copy
import numpy as np
from lib import mps as mpslib
import scipy.linalg
import MPSsolver
from elementop import *
import constant
from ephMPS import RK
from ephMPS.utils.utils import *
from ephMPS import mpompsmat
from lib import tensor as tensorlib
import numpy.linalg
import scipy.integrate

class prop_setup(object):
    def __init__(self, rk):
        self.rk = rk

def Exact_Spectra(spectratype, mol, pbond, iMPS, dipoleMPO, nsteps, dt,\
        temperature, GSshift=0.0, EXshift=0.0):
    '''
    0T emission spectra exact propagator
    the bra part e^iEt is negected to reduce the osillation
    and 
    for single molecule, the EX space propagator e^iHt is local, and so exact
    
    GS/EXshift is the ground/excited state space energy shift
    the aim is to reduce the oscillation of the correlation fucntion

    support:
    all cases: 0Temi
    1mol case: 0Temi, TTemi, 0Tabs, TTabs
    '''
    
    assert spectratype in ["emi","abs"]
    
    if spectratype == "emi":
        space1 = "EX"
        space2 = "GS"
        shift1 = EXshift
        shift2 = GSshift

        if temperature != 0:
            assert len(mol) == 1
    else:
        assert len(mol) == 1
        space1 = "GS"
        space2 = "EX"
        shift1 = GSshift
        shift2 = EXshift
    
    if temperature != 0:
        beta = constant.T2beta(temperature)
        print "beta=", beta
        thermalMPO, thermalMPOdim = ExactPropagatorMPO(mol, pbond, -beta/2.0, space=space1, shift=shift1)
        ketMPS = mpslib.mapply(thermalMPO, iMPS)
        Z = mpslib.dot(mpslib.conj(ketMPS),ketMPS)
        print "partition function Z(beta)/Z(0)", Z
    else:
        ketMPS = iMPS
        Z = 1.0
    
    AketMPS = mpslib.mapply(dipoleMPO, ketMPS)
    
    if temperature != 0:
        braMPS = mpslib.add(ketMPS, None)
    else:
        AbraMPS = mpslib.add(AketMPS, None)

    t = 0.0
    autocorr = []
    propMPO1, propMPOdim1 = ExactPropagatorMPO(mol, pbond, -1.0j*dt, space=space1, shift=shift1)
    propMPO2, propMPOdim2 = ExactPropagatorMPO(mol, pbond, -1.0j*dt, space=space2, shift=shift2)

    # we can reconstruct the propagator each time if there is accumulated error
    
    for istep in xrange(nsteps):
        if istep !=0:
            AketMPS = mpslib.mapply(propMPO2, AketMPS)
            if temperature != 0:
                braMPS = mpslib.mapply(propMPO1, braMPS)
        
        if temperature != 0:
            AbraMPS = mpslib.mapply(dipoleMPO, braMPS)
        
        ft = mpslib.dot(mpslib.conj(AbraMPS),AketMPS)
        autocorr.append(ft/Z)
        autocorr_store(autocorr, istep)

    return autocorr


def ExactPropagatorMPO(mol, pbond, x, space="GS", QNargs=None, shift=0.0):
    '''
    construct the GS space propagator e^{xH} exact MPO 
    H=\sum_{in} \omega_{in} b^\dagger_{in} b_{in}
    fortunately, the H is local. so e^{xH} = e^{xh1}e^{xh2}...e^{xhn}
    the bond dimension is 1
    shift is the a constant for H+shift
    '''
    assert space in ["GS","EX"]

    nmols = len(mol)
    MPOdim = [1] *(len(pbond)+1)
    MPOQN = [[0]]*(len(pbond)+1)
    MPOQNidx = len(pbond)-1
    MPOQNtot = 0

    MPO = []
    impo = 0
    for imol in xrange(nmols):
        mpo = np.zeros([MPOdim[impo],pbond[impo],pbond[impo],MPOdim[impo+1]],dtype=np.complex128)
        for ibra in xrange(pbond[impo]):
            # caution: there is problem here, for EX sapce a^\dagger a, only
            # ibra == 1, mpo[0,1,1,0] = 1.0, so the MPO is still dim = 2. But
            # practically, ibra=0 is not used at all, so mpo[0,0,0,0] is not
            # important.
            mpo[0,ibra,ibra,0] = 1.0   
        MPO.append(mpo)
        impo += 1

        for iph in xrange(mol[imol].nphs):
            if space == "EX":
                # for the EX space, with quasiboson algorithm, the b^\dagger + b
                # operator is not local anymore.
                assert mol[imol].ph[iph].nqboson == 1
                # construct the matrix exponential by diagonalize the matrix first
                Hmpo = np.zeros([pbond[impo],pbond[impo]])
                
                for ibra in xrange(pbond[impo]):
                    for iket in xrange(pbond[impo]):
                        Hmpo[ibra,iket] = PhElementOpera("b^\dagger b", ibra, iket) *mol[imol].ph[iph].omega[0] \
                                           + PhElementOpera("(b^\dagger + b)^3",ibra, iket)*\
                                          mol[imol].ph[iph].force3rd[0] * (0.5/mol[imol].ph[iph].omega[0])**1.5 \
                                           + PhElementOpera("b^\dagger + b",ibra, iket) * \
                                          (mol[imol].ph[iph].omega[1]**2 / np.sqrt(2.*mol[imol].ph[iph].omega[0])* -mol[imol].ph[iph].dis[1] \
                                           + 3.0*mol[imol].ph[iph].dis[1]**2*mol[imol].ph[iph].force3rd[1]/\
                                           np.sqrt(2.*mol[imol].ph[iph].omega[0])) \
                                           + PhElementOpera("(b^\dagger + b)^2",ibra, iket) * \
                                          (0.25*(mol[imol].ph[iph].omega[1]**2-mol[imol].ph[iph].omega[0]**2)/mol[imol].ph[iph].omega[0]\
                                           - 1.5*mol[imol].ph[iph].dis[1]*mol[imol].ph[iph].force3rd[1]/mol[imol].ph[iph].omega[0])\
                                           + PhElementOpera("(b^\dagger + b)^3",ibra, iket) * \
                                           (mol[imol].ph[iph].force3rd[1]-mol[imol].ph[iph].force3rd[0])*(0.5/mol[imol].ph[iph].omega[0])**1.5

                w, v = scipy.linalg.eigh(Hmpo)
                Hmpo = np.diag(np.exp(x*w))
                Hmpo = v.dot(Hmpo)
                Hmpo = Hmpo.dot(v.T)

                mpo = np.zeros([MPOdim[impo],pbond[impo],pbond[impo],MPOdim[impo+1]],dtype=np.complex128)
                mpo[0,:,:,0] = Hmpo
                
                MPO.append(mpo)
                impo += 1

            elif space == "GS":
                # for the ground state space, yet doesn't support 3rd force
                # potential quasiboson algorithm
                for i in mol[imol].ph[iph].force3rd:
                    anharmo = not np.allclose(mol[imol].ph[iph].force3rd[i]*mol[imol].ph[iph].dis[i]/mol[imol].ph[iph].omega[i],0.0)
                    if anharmo == True:
                        break
                
                if anharmo == False:
                    for iboson in xrange(mol[imol].ph[iph].nqboson):
                        mpo = np.zeros([MPOdim[impo],pbond[impo],pbond[impo],MPOdim[impo+1]],dtype=np.complex128)

                        for ibra in xrange(pbond[impo]):
                            mpo[0,ibra,ibra,0] = np.exp(x*mol[imol].ph[iph].omega[0] * \
                                        float(mol[imol].ph[iph].base)**(mol[imol].ph[iph].nqboson-iboson-1)*float(ibra))

                        MPO.append(mpo)
                        impo += 1
                else:
                    assert mol[imol].ph[iph].nqboson == 1
                    # construct the matrix exponential by diagonalize the matrix first
                    Hmpo = np.zeros([pbond[impo],pbond[impo]])
                    for ibra in xrange(pbond[impo]):
                        for iket in xrange(pbond[impo]):
                            Hmpo[ibra,iket] = PhElementOpera("b^\dagger b", ibra, iket) *mol[imol].ph[iph].omega[0] \
                                               + PhElementOpera("(b^\dagger + b)^3",ibra, iket)*\
                                              mol[imol].ph[iph].force3rd[0] * (0.5/mol[imol].ph[iph].omega[0])**1.5 

                    w, v = scipy.linalg.eigh(Hmpo)
                    Hmpo = np.diag(np.exp(x*w))
                    Hmpo = v.dot(Hmpo)
                    Hmpo = Hmpo.dot(v.T)

                    mpo = np.zeros([MPOdim[impo],pbond[impo],pbond[impo],MPOdim[impo+1]],dtype=np.complex128)
                    mpo[0,:,:,0] = Hmpo
                    
                    MPO.append(mpo)
                    impo += 1
    
    # shift the H by plus a constant
    MPO = mpslib.scale(MPO,np.exp(shift*x))

    if QNargs is not None:
        MPO = [MPO, MPOQN, MPOQNidx, MPOQNtot]

    return MPO, MPOdim 


# only for debug reason
def wfnPropagation(setup, iMPS, HMPO, nsteps, dt, ephtable, thresh=0, \
        cleanexciton=None, compress_method="svd", QNargs=None):
    '''
    simple wavefunction propagation through Runge-Kutta methods
    '''
    rk = setup.rk
    
    ketMPS = mpslib.add(iMPS, None, QNargs=QNargs)
    Hset = [] # energy
    Vset = [] # overlap
    for isteps in xrange(nsteps):
        if isteps != 0:
            ketMPS = tMPS(rk, ketMPS, HMPO, dt, ephtable, thresh=thresh, \
                cleanexciton=cleanexciton, compress_method=compress_method, \
                QNargs=QNargs)
        
        Hset.append(mpslib.dot(mpslib.conj(ketMPS,QNargs=QNargs), \
                mpslib.mapply(HMPO, ketMPS, QNargs=QNargs), QNargs=QNargs))
        Vset.append(mpslib.dot(mpslib.conj(ketMPS,QNargs=QNargs), \
                ketMPS, QNargs=QNargs))
    
    return Hset, Vset


def ZeroTCorr(setup, iMPS, HMPO, dipoleMPO, nsteps, dt, ephtable, thresh=0, \
        cleanexciton=None, algorithm=1,\
        compress_method="svd", QNargs=None, approxeiHt=None, scheme="P&C"):
    '''
    the bra part e^iEt is negected to reduce the oscillation
    algorithm:
    algorithm 1 is the only propagte ket in 0, dt, 2dt
    algorithm 2 is propagte bra and ket in 0, dt, 2dt (in principle, with
    same calculation cost, more accurate, because the bra is also entangled,
    the entanglement is not only in ket)
    compress_method:  svd or variational
    cleanexciton: every time step propagation clean the good quantum number to
    discard the numerical error
    thresh: the svd threshold in svd or variational compress
    '''
    rk = setup.rk

    AketMPS = mpslib.mapply(dipoleMPO, iMPS, QNargs=QNargs)
    # store the factor and normalize the AketMPS, factor is the length of AketMPS
    factor = mpslib.norm(AketMPS, QNargs=QNargs)
    print "factor",factor
    AketMPS = mpslib.scale(AketMPS, 1./factor, QNargs=QNargs)
    
    if compress_method == "variational":
        AketMPS = mpslib.canonicalise(AketMPS, 'l', QNargs=QNargs)
    AbraMPS = mpslib.add(AketMPS,None, QNargs=QNargs)

    autocorr = []
    t = 0.0
    
    if approxeiHt is not None:
        approxeiHpt = ApproxPropagatorMPO(rk, HMPO, dt, ephtable, \
                thresh=approxeiHt, compress_method=compress_method, QNargs=QNargs)
        approxeiHmt = ApproxPropagatorMPO(rk, HMPO, -dt, ephtable,\
                thresh=approxeiHt, compress_method=compress_method, QNargs=QNargs)
    else:
        approxeiHpt = None
        approxeiHmt = None

    for istep in xrange(nsteps):
        if istep != 0:
            t += dt
            if algorithm == 1:
                AketMPS = tMPS(rk, AketMPS, HMPO, dt, ephtable, thresh=thresh, \
                    cleanexciton=cleanexciton, compress_method=compress_method, \
                    QNargs=QNargs, approxeiHt=approxeiHpt, normalize=1., \
                    scheme=scheme, prefix=scheme)
            if algorithm == 2:
                if istep % 2 == 1:
                    AketMPS = tMPS(rk, AketMPS, HMPO, dt, ephtable, thresh=thresh, \
                        cleanexciton=cleanexciton, compress_method=compress_method, QNargs=QNargs,\
                        approxeiHt=approxeiHpt, normalize=1., scheme=scheme, \
                        prefix=scheme+"1")
                else:
                    AbraMPS = tMPS(rk, AbraMPS, HMPO, -dt, ephtable, thresh=thresh, \
                        cleanexciton=cleanexciton, compress_method=compress_method, QNargs=QNargs,\
                        approxeiHt=approxeiHmt, normalize=1., scheme=scheme,\
                        prefix=scheme+"2")
        ft = mpslib.dot(mpslib.conj(AbraMPS,QNargs=QNargs),AketMPS, QNargs=QNargs)*factor**2
        wfn_store(AbraMPS, istep, str(dt)+str(thresh)+"AbraMPS.pkl")
        wfn_store(AketMPS, istep, str(dt)+str(thresh)+"AketMPS.pkl")
        
        autocorr.append(ft)
        autocorr_store(autocorr, istep)

    return autocorr


def ApproxPropagatorMPO(rk, HMPO, dt, ephtable,thresh=0, \
        compress_method="svd", QNargs=None):
    '''
    e^-iHdt : approximate propagator MPO from Runge-Kutta methods
    '''

    # Identity operator 
    if QNargs is not None:
        nmpo = len(HMPO[0])
    else:
        nmpo = len(HMPO)

    MPOdim = [1] * (nmpo+1)
    MPOQN = [[0]] * (nmpo+1)
    MPOQNidx = nmpo-1
    MPOQNtot = 0
    
    IMPO = []
    for impo in xrange(nmpo):
        if QNargs is not None:
            mpo = np.ones([1,HMPO[0][impo].shape[1],1], dtype=np.complex128)
        else:
            mpo = np.ones([1,HMPO[impo].shape[1],1], dtype=np.complex128)
        IMPO.append(mpo)
    IMPO = hilbert_to_liouville(IMPO)
    
    QNargslocal = copy.deepcopy(QNargs)
    
    if QNargs is not None:
        IMPO = [IMPO, MPOQN, MPOQNidx, MPOQNtot]
        # a real MPO compression
        QNargslocal[1] = True

    approxMPO = tMPS(rk, IMPO, HMPO, dt, ephtable, thresh=thresh, \
        compress_method=compress_method, QNargs=QNargslocal)
    
    print "approx propagator thresh:", thresh
    if QNargs is not None:
        print "approx propagator dim:", [mpo.shape[0] for mpo in approxMPO[0]]
    else:
        print "approx propagator dim:", [mpo.shape[0] for mpo in approxMPO]

    chkIden = mpslib.mapply(mpslib.conj(approxMPO,QNargs=QNargs), approxMPO, QNargs=QNargs)
    print "approx propagator Identity error", np.sqrt(mpslib.distance(chkIden, IMPO, QNargs=QNargs) /\
        mpslib.dot(IMPO, IMPO, QNargs=QNargs))
    
    return approxMPO


def ML_tMPS():
    '''
    The procedure is 
    (1) MPS -> ML-MPS -> ML + new MPS
    (2) MPO -> ML-MPO-ML -> new MPO
    (3) new MPO +  new MPS -> propagated MPS
    (4) ML + propagated MPS -> MPS in original basis
    '''

def tMPS(rk, MPS, MPO, dt, ephtable, thresh=0, \
        cleanexciton=None, compress_method="svd", QNargs=None, approxeiHt=None,\
        normalize=None, swap=False, scheme="P&C", prefix="",opt=False):
    '''
        core function to do time propagation
        swap = False  e^-iHt MPO
        swap = True   MPO * e^-iHt
    '''

    if scheme == "P&C":
        # propagate and compress
        
        if approxeiHt is None:

            termlist = [MPS]
            for iterm in range(rk.stage):
                # when using variational method, the input MPS is L-canonicalise
                # (in principle doesn't matter whether L-canonicalise, in practice, about
                # the initial guess of the compress wfn)
                if swap == False:
                    termlist.append(mpslib.contract(MPO, termlist[iterm], 'l', thresh, compress_method=compress_method, QNargs=QNargs))
                else:    
                    termlist.append(mpslib.contract(termlist[iterm], MPO, 'l', thresh, compress_method=compress_method, QNargs=QNargs))
            
            scaletermlist = []
            for iterm in xrange(rk.stage+1):
                scaletermlist.append(mpslib.scale(termlist[iterm],
                    (-1.0j*dt)**iterm*rk.Te_coeff()[iterm], QNargs=QNargs))
            del termlist
            
            if rk.adaptive == True:
                nterms = rk.stage
            else:
                nterms = rk.stage+1

            MPSnew = scaletermlist[0]
            if opt == False:
                for iterm in xrange(1,nterms):
                    MPSnew = mpslib.add(MPSnew, scaletermlist[iterm], QNargs=QNargs)
        
                MPSnew = mpslib.canonicalise(MPSnew, 'r', QNargs=QNargs)
                MPSnew = mpslib.compress(MPSnew, 'r', trunc=thresh, QNargs=QNargs)

            elif opt == "greedy":
                for iterm in xrange(1,nterms):
                    MPSnew = mpslib.add(MPSnew, scaletermlist[iterm], QNargs=QNargs)
                    MPSnew = mpslib.canonicalise(MPSnew, 'r', QNargs=QNargs)
                    MPSnew = mpslib.compress(MPSnew, 'r', trunc=thresh, QNargs=QNargs)
            
            if rk.adaptive == True:
                MPS_adap = mpslib.add(MPSnew, scaletermlist[-1], QNargs=QNargs)
                MPS_adap = mpslib.canonicalise(MPS_adap, 'r', QNargs=QNargs)
                MPS_adap = mpslib.compress(MPS_adap, 'r', trunc=thresh, QNargs=QNargs, normalize=normalize)
            
            del scaletermlist
            
            # normalize MPSnew
            norm = mpslib.norm(MPSnew, QNargs=QNargs)
            MPSnew = mpslib.scale(MPSnew, normalize/norm, QNargs=QNargs)
            
            if rk.adaptive == True:
                # only suit for RKF45
                dot = mpslib.dot(mpslib.conj(MPSnew, QNargs=QNargs), MPS_adap, QNargs=QNargs)
                p= (rk.rtol/np.sqrt(abs(2.-2*dot.real)+1e-30))**(1./(rk.order[0]+1)) * 0.8
                MPnew = MPS_adap
        else:
            if swap == False:
                MPSnew = mpslib.contract(approxeiHt, MPS, 'r', thresh, compress_method=compress_method, QNargs=QNargs)
            else: 
                MPSnew = mpslib.contract(MPS, approxeiHt, 'r', thresh, compress_method=compress_method, QNargs=QNargs)

        if (cleanexciton is not None) and (QNargs is None):
            # clean the MPS according to quantum number constrain
            MPSnew = MPSsolver.clean_MPS('R', MPSnew, ephtable, cleanexciton)
            # compress the clean MPS
            MPSnew = mpslib.compress(MPSnew, 'r', trunc=thresh)
        
        if QNargs is None:
            print "tMPS dim:", [mps.shape[0] for mps in MPSnew] + [1]
        else:
            print "tMPS dim:", [mps.shape[0] for mps in MPSnew[0]] + [1]
    
    elif scheme == "TDVP_PS":
        # TDVP projector splitting
        MPSnew = []
        
        # make sure the input MPS is L-orthogonal
        # in the spectrum calculation set compress_method = "variational"
        MPS =  mpslib.canonicalise(MPS,"l")
        nMPS = len(MPS)
        # construct the environment matrix
        if mpompsmat.Enviro_check("L", range(nMPS-1), prefix=prefix) == False:
            print "check_Enviro False"
            mpompsmat.construct_enviro(MPS, mpslib.conj(MPS), MPO, "L", prefix=prefix)
        
        MPSold = copy.deepcopy(MPS)
        # initial matrix   
        ltensor = np.ones((1,1,1))
        rtensor = np.ones((1,1,1))
        
        loop = [['R',i] for i in xrange(nMPS-1,-1,-1)] + [['L',i] for i in xrange(0,nMPS)]
        for system, imps in loop:
            if system == "R":
                lmethod, rmethod = "Enviro", "System"
                ltensor = mpompsmat.GetLR('L', imps-1, MPS, mpslib.conj(MPS), MPO, \
                        itensor=ltensor, method=lmethod, prefix=prefix)
            else:
                lmethod, rmethod = "System", "Enviro"
                rtensor = mpompsmat.GetLR('R', imps+1, MPS, mpslib.conj(MPS), MPO, \
                        itensor=rtensor, method=rmethod, prefix=prefix)
            
            def hop(mps):
                #S-a   l-S
                #    d  
                #O-b-O-f-O
                #    e 
                #S-c   k-S
                
                if mps.ndim == 3:
                    path = [([0, 1],"abc, cek -> abek"),\
                            ([2, 0],"abek, bdef -> akdf"),\
                            ([1, 0],"akdf, lfk -> adl")]
                    HC = tensorlib.multi_tensor_contract(path, ltensor,
                            mps, MPO[imps], rtensor)
                
                #S-a   l-S
                #    d  
                #O-b-O-f-O
                #    e 
                #S-c   k-S
                #    g   
                elif mps.ndim == 4:
                    path = [([0, 1],"abc, bdef -> acdef"),\
                            ([2, 0],"acdef, cegk -> adfgk"),\
                            ([1, 0],"adfgk, lfk -> adgl")]
                    HC = tensorlib.multi_tensor_contract(path, ltensor,
                            MPO[imps], mps, rtensor)
                return HC
            
            def hop_svt(mps):
                #S-a   l-S
                #      
                #O-b - b-O
                #     
                #S-c   k-S
                
                path = [([0, 1],"abc, ck -> abk"),\
                        ([1, 0],"abk, lbk -> al")]
                HC = tensorlib.multi_tensor_contract(path, ltensor,
                        mps, rtensor)
                return HC
            
            shape = list(MPS[imps].shape)
            
            def func(t, y):
                return hop(y.reshape(shape)).ravel()/1.0j
            sol = scipy.integrate.solve_ivp(func, (0,dt/2.), MPS[imps].ravel(), method="RK45")
            print "nsteps for MPS[imps]:",len(sol.t)
            mps_t = sol.y[:,-1].reshape(shape)
            
            if system == "L" and imps != len(MPS)-1:
                # updated imps site
                u,vt = scipy.linalg.qr(mps_t.reshape(-1,shape[-1]), mode="economic")
                MPS[imps] = u.reshape(shape[:-1]+[-1])

                ltensor = mpompsmat.GetLR('L', imps, MPS, mpslib.conj(MPS), MPO, \
                        itensor=ltensor, method="System",prefix=prefix)
                
                # reverse update svt site
                shape_svt = vt.shape
                def func_svt(t, y):
                    return hop_svt(y.reshape(shape_svt)).ravel()/1.0j
                
                sol_svt = scipy.integrate.solve_ivp(func_svt, (0,-dt/2), vt.ravel(), method="RK45")
                print "nsteps for svt:",len(sol_svt.t)
                MPS[imps+1] = np.tensordot(sol_svt.y[:,-1].reshape(shape_svt), MPS[imps+1], axes=(1,0))
            
            elif system == "R" and imps != 0:
                # updated imps site
                u,vt = scipy.linalg.rq(mps_t.reshape(shape[0], -1), mode="economic")
                MPS[imps] = vt.reshape([-1]+shape[1:])

                rtensor = mpompsmat.GetLR('R', imps, MPS, mpslib.conj(MPS), MPO, \
                        itensor=rtensor, method="System", prefix=prefix)
                
                # reverse update u site
                shape_u = u.shape
                def func_u(t, y):
                    return hop_svt(y.reshape(shape_u)).ravel()/1.0j
                
                sol_u = scipy.integrate.solve_ivp(func_u, (0,-dt/2), u.ravel(), method="RK45")
                print "nsteps for u:",len(sol_u.t)
                MPS[imps-1] = np.tensordot(MPS[imps-1], sol_u.y[:,-1].reshape(shape_u), axes=(-1,0))
            
            else:
                MPS[imps] = mps_t
            
        MPSnew = MPS
        if MPSnew[0].ndim == 3:
            # normalize
            norm = mpslib.norm(MPSnew)
            print "norm", norm
            MPSnew = mpslib.scale(MPSnew, 1./norm)
        
        print "tMPS dim:", [mps.shape[0] for mps in MPSnew] + [1]
    
    elif scheme == "TDVP_MCTDH":
        # TDVP for original MCTDH

        MPSnew = []
        if mpslib.is_left_canonical(MPS) == False:
            print "MPS is not left canonical!"
            MPS =  mpslib.canonicalise(MPS,"l")
        
        # TODO, reuse the last step environment, L-R, R-L
        # construct the environment matrix
        mpompsmat.construct_enviro(MPS, mpslib.conj(MPS), MPO, "R")
        
        # initial matrix   
        ltensor = np.ones((1,1,1))
        rtensor = np.ones((1,1,1))

        for imps in range(len(MPS)):
            ltensor = mpompsmat.GetLR('L', imps-1, MPS, mpslib.conj(MPS), MPO, \
                    itensor=ltensor, method="System")
            rtensor = mpompsmat.GetLR('R', imps+1, MPS, mpslib.conj(MPS), MPO, \
                    itensor=rtensor, method="Enviro")
            # density matrix
            S = mpslib.transferMat(MPS, mpslib.conj(MPS), "R", imps+1)
            
            epsilon = 1e-10
            w, u = scipy.linalg.eigh(S)
            w = w + epsilon * np.exp(-w/epsilon)
            print "sum w=", np.sum(w)
            #S  = u.dot(np.diag(w)).dot(np.conj(u.T))
            S_inv  = u.dot(np.diag(1./w)).dot(np.conj(u.T))
            
            # pseudo inverse 
            #S_inv = scipy.linalg.pinvh(S,rcond=1e-2)

            def projector(mps):
                # projector
                proj = np.tensordot(mps,np.conj(mps),axes=(2,2))
                Iden = np.diag(np.ones(np.prod(proj.shape[:2]))).reshape(proj.shape)
                proj = Iden - proj
                return proj
            
            def hop(mps):
                #S-a   l-S
                #    d  
                #O-b-O-f-O
                #    e 
                #S-c   k-S
                
                if mps.ndim == 3:
                    path = [([0, 1],"abc, cek -> abek"),\
                            ([2, 0],"abek, bdef -> akdf"),\
                            ([1, 0],"akdf, lfk -> adl")]
                    HC = tensorlib.multi_tensor_contract(path, ltensor,
                            mps, MPO[imps], rtensor)
                
                #S-a   l-S
                #    d  
                #O-b-O-f-O
                #    e 
                #S-c   k-S
                #    g   
                elif mps.ndim == 4:
                    path = [([0, 1],"abc, bdef -> acdef"),\
                            ([2, 0],"acdef, cegk -> adfgk"),\
                            ([1, 0],"adfgk, lfk -> adgl")]
                    HC = tensorlib.multi_tensor_contract(path, ltensor,
                            MPO[imps], mps, rtensor)
                return HC
            
            shape = MPS[imps].shape
            
            def func(t, y):
                y0 = y.reshape(shape)
                HC = hop(y0)
                if imps != len(MPS)-1:
                    proj = projector(y0)
                    if y0.ndim == 3:
                        HC = np.tensordot(proj,HC,axes=([2,3],[0,1]))
                        HC = np.tensordot(proj,HC,axes=([2,3],[0,1]))
                    elif y0.ndim == 4:
                        HC = np.tensordot(proj,HC,axes=([3,4,5],[0,1,2]))
                        HC = np.tensordot(proj,HC,axes=([3,4,5],[0,1,2]))

                return np.tensordot(HC, S_inv, axes=(-1,0)).ravel()/1.0j
            
            sol = scipy.integrate.solve_ivp(func,(0,dt), MPS[imps].ravel(),method="RK45")
            print "CMF steps:", len(sol.t)
            MPSnew.append(sol.y[:,-1].reshape(shape))
            print "orthogonal1", np.allclose(np.tensordot(MPSnew[imps],
                np.conj(MPSnew[imps]), axes=([0,1],[0,1])),
                np.diag(np.ones(MPSnew[imps].shape[2])))
        
        norm = mpslib.norm(MPSnew)
        MPSnew = mpslib.scale(MPSnew, 1./norm)
        print "norm", norm
        print "tMPS dim:", [mps.shape[0] for mps in MPSnew] + [1]
    
    elif scheme == "TDVP_MCTDHnew":
        # new regularization scheme
        # JCP 148, 124105 (2018)
        # JCP 149, 044119 (2018)

        MPSnew = []
        if mpslib.is_right_canonical(MPS) == False:
            print "MPS is not left canonical!"
            MPS =  mpslib.canonicalise(MPS,"r")
        
        # construct the environment matrix
        mpompsmat.construct_enviro(MPS, mpslib.conj(MPS), MPO, "R")
        
        # initial matrix   
        ltensor = np.ones((1,1,1))
        rtensor = np.ones((1,1,1))
        
        for imps in range(len(MPS)):
            shape = list(MPS[imps].shape)
            
            u, s, vt = scipy.linalg.svd(MPS[imps].reshape(-1, shape[-1]), full_matrices=False)
            MPS[imps] = u.reshape(shape[:-1]+[-1])
            
            ltensor = mpompsmat.GetLR('L', imps-1, MPS, mpslib.conj(MPS), MPO, \
                    itensor=ltensor, method="System")
            rtensor = mpompsmat.GetLR('R', imps+1, MPS, mpslib.conj(MPS), MPO, \
                    itensor=rtensor, method="Enviro")
            
            epsilon = 1e-10
            epsilon = np.sqrt(epsilon)
            s = s + epsilon * np.exp(-s/epsilon)
            
            svt = np.diag(s).dot(vt)
            
            rtensor = np.tensordot(rtensor, svt, axes=(2, 1))
            rtensor = np.tensordot(np.conj(vt), rtensor, axes=(1, 0))

            if imps != len(MPS)-1:
                MPS[imps+1] = np.tensordot(svt, MPS[imps+1], axes=(-1,0))
            
            # density matrix
            S = s*s
            print "sum density matrix", np.sum(S)

            S_inv = np.diag(1./s)
            
            def projector(mps):
                # projector
                proj = np.tensordot(mps, np.conj(mps),axes=(-1,-1))
                Iden = np.diag(np.ones(np.prod(mps.shape[:-1]))).reshape(proj.shape)
                proj = Iden - proj
                return proj
            
            def hop(mps):
                #S-a   l-S
                #    d  
                #O-b-O-f-O
                #    e 
                #S-c   k-S
                if mps.ndim == 3:
                    path = [([0, 1],"abc, cek -> abek"),\
                            ([2, 0],"abek, bdef -> akdf"),\
                            ([1, 0],"akdf, lfk -> adl")]
                    HC = tensorlib.multi_tensor_contract(path, ltensor,
                            mps, MPO[imps], rtensor)
                
                #S-a   l-S
                #    d  
                #O-b-O-f-O
                #    e 
                #S-c   k-S
                #    g   
                elif mps.ndim == 4:
                    path = [([0, 1],"abc, bdef -> acdef"),\
                            ([2, 0],"acdef, cegk -> adfgk"),\
                            ([1, 0],"adfgk, lfk -> adgl")]
                    HC = tensorlib.multi_tensor_contract(path, ltensor,
                            MPO[imps], mps, rtensor)
                return HC
            
            shape = MPS[imps].shape
            
            def func(t, y):
                y0 = y.reshape(shape)
                HC = hop(y0)
                if imps != len(MPS)-1:
                    proj = projector(y0)
                    if y0.ndim == 3:
                        HC = np.tensordot(proj,HC,axes=([2,3],[0,1]))
                        HC = np.tensordot(proj,HC,axes=([2,3],[0,1]))
                    elif y0.ndim == 4:
                        HC = np.tensordot(proj,HC,axes=([3,4,5],[0,1,2]))
                        HC = np.tensordot(proj,HC,axes=([3,4,5],[0,1,2]))
                return np.tensordot(HC, S_inv, axes=(-1,0)).ravel()/1.0j
            
            sol = scipy.integrate.solve_ivp(func,(0,dt), MPS[imps].ravel(),method="RK45")
            print "CMF steps:", len(sol.t)
            mps = sol.y[:,-1].reshape(shape)

            if imps == len(MPS)-1:
                print "s0", imps, s[0]
                MPSnew.append(mps*s[0])
            else:
                MPSnew.append(mps)
            
            #print "orthogonal1", np.allclose(np.tensordot(MPSnew[imps],
            #    np.conj(MPSnew[imps]), axes=([0,1],[0,1])),
            #    np.diag(np.ones(MPSnew[imps].shape[2])))
        
        if MPSnew[0].ndim == 3:
            norm = mpslib.norm(MPSnew)
            MPSnew = mpslib.scale(MPSnew, 1./norm)
            print "norm", norm
        print "tMPS dim:", [mps.shape[0] for mps in MPSnew] + [1]
    
    if rk.adaptive == False:
        return MPSnew
    else:
        return MPSnew, p


def FiniteT_spectra(setup, spectratype, mol, pbond, iMPO, HMPO, dipoleMPO, nsteps, dt,\
        ephtable, insteps=0, thresh=0, ithresh=1e-3, temperature=298,\
        algorithm=2, compress_method="svd", QNargs=None, \
        approxeiHt=None, GSshift=0.0, cleanexciton=None, scheme="P&C",\
        restart=False):
    '''
    finite temperature propagation
    only has algorithm 2, two way propagator
    '''
    
    rk = setup.rk

    assert algorithm == 2
    assert spectratype in ["abs","emi"]
    
    beta = constant.T2beta(temperature)
    print "beta=", beta
    
    if restart == False:
        # e^{\-beta H/2} \Psi
        if spectratype == "emi":
            ketMPO = thermal_prop(rk, iMPO, HMPO, insteps, ephtable, thresh=ithresh,\
                    temperature=temperature, compress_method=compress_method,\
                    QNargs=QNargs, approxeiHt=approxeiHt, normalize=1.0)
        elif spectratype == "abs":
            thermalMPO, thermalMPOdim = ExactPropagatorMPO(mol, pbond, -beta/2.0,\
                    QNargs=QNargs, shift=GSshift)
            ketMPO = mpslib.mapply(thermalMPO,iMPO, QNargs=QNargs)
        
        #\Psi e^{\-beta H} \Psi
        norm = mpslib.norm(ketMPO, QNargs=QNargs)
        print "partition function", norm**2
        
        ketMPO = mpslib.scale(ketMPO, 1./norm, QNargs=QNargs)
        print "norm:", mpslib.norm(ketMPO, QNargs=QNargs)
        

        if spectratype == "abs":
            ketMPO = mpslib.mapply(dipoleMPO, ketMPO, QNargs=QNargs)
        else:
            dipoleMPOdagger = mpslib.conjtrans(dipoleMPO, QNargs=QNargs)
            if QNargs is not None:
                dipoleMPOdagger[1] = [[0]*len(impsdim) for impsdim in dipoleMPO[1]]
                dipoleMPOdagger[3] = 0
            ketMPO = mpslib.mapply(ketMPO, dipoleMPOdagger, QNargs=QNargs)
        
        # normalize
        factor = mpslib.norm(ketMPO, QNargs=QNargs)
        ketMPO = mpslib.scale(ketMPO, 1./factor, QNargs=QNargs)
        print ("factor", factor)

        braMPO = mpslib.add(ketMPO, None, QNargs=QNargs)
    
    elif restart == True:
        with open("braMPO.pkl","rb") as f:
            braMPO = pickle.load(f)
        with open("ketMPO.pkl","rb") as f:
            ketMPO = pickle.load(f)
        factor = 1.0

    if compress_method == "variational":
        ketMPO = mpslib.canonicalise(ketMPO, 'l', QNargs=QNargs)
        braMPO = mpslib.canonicalise(braMPO, 'l', QNargs=QNargs)

    if approxeiHt is not None:
        approxeiHpt = ApproxPropagatorMPO(rk, HMPO, dt, ephtable,\
                thresh=approxeiHt, compress_method=compress_method, QNargs=QNargs)
        approxeiHmt = ApproxPropagatorMPO(rk, HMPO, -dt, ephtable,\
                thresh=approxeiHt, compress_method=compress_method, QNargs=QNargs)
    else:
        approxeiHpt = None
        approxeiHmt = None
    
    autocorr = []
    t = 0.0
    exacteiHpt, exacteiHptdim = ExactPropagatorMPO(mol, pbond, -1.0j*dt,\
            QNargs=QNargs, shift=GSshift)
    exacteiHmt, exacteiHmtdim = ExactPropagatorMPO(mol, pbond, 1.0j*dt,\
            QNargs=QNargs, shift=GSshift)

    for istep in xrange(nsteps):
        if istep != 0:
            t += dt
            # for emi bra and ket is conjugated
            if istep % 2 == 0:
                braMPO = mpslib.mapply(braMPO, exacteiHpt, QNargs=QNargs) 
                braMPO = tMPS(rk, braMPO, HMPO, -dt, ephtable, \
                       thresh=thresh, cleanexciton=1, compress_method=compress_method, \
                       QNargs=QNargs, approxeiHt=approxeiHmt, scheme=scheme,\
                       prefix=scheme+"2", normalize=1.,)
            else:
                ketMPO = mpslib.mapply(ketMPO, exacteiHmt, QNargs=QNargs) 
                ketMPO = tMPS(rk, ketMPO, HMPO, dt, ephtable, \
                       thresh=thresh, cleanexciton=1, compress_method=compress_method, \
                       QNargs=QNargs, approxeiHt=approxeiHpt, scheme=scheme,\
                       prefix=scheme+"1", normalize=1.)

        
        ft = mpslib.dot(mpslib.conj(braMPO, QNargs=QNargs),ketMPO, QNargs=QNargs) * factor**2
        if spectratype == "emi":
            ft = np.conj(ft)
        
        wfn_store(braMPO, istep, "braMPO.pkl")
        wfn_store(ketMPO, istep, "ketMPO.pkl")
        autocorr.append(ft)
        autocorr_store(autocorr, istep)
    
    return autocorr  


def thermal_prop(rk, iMPO, HMPO, nsteps, ephtable, thresh=0, temperature=298, \
       compress_method="svd", QNargs=None, approxeiHt=None, normalize=None):
    '''
    do imaginary propagation
    '''
    
    beta = constant.T2beta(temperature)
    print "beta=", beta
    dbeta = beta/float(nsteps)
    
    if approxeiHt is not None:
        approxeiHpt = ApproxPropagatorMPO(rk, HMPO, -0.5j*dbeta, ephtable,\
                thresh=approxeiHt, compress_method=compress_method, QNargs=QNargs)
    else:
        approxeiHpt = None
    
    ketMPO = mpslib.add(iMPO, None, QNargs=QNargs)

    #for istep in xrange(nsteps):
    #    it += dbeta
    #    ketMPO = tMPS(ketMPO, HMPO, -0.5j*dbeta, ephtable, propagation_c,thresh=thresh,\
    #            cleanexciton=1, compress_method=compress_method, QNargs=QNargs,\
    #            approxeiHt=approxeiHpt, normalize=normalize,adaptive=1.0)
    
    beta0 = 0.0
    start = False
    istep = 0
    if rk.adaptive == True:
        p = 0.9
    else:
        p = 1
    loop = True

    while loop:
        if start == False:
            # estimate an appropriate dbeta
            if p >= 1 and p < 1.5:
                start = True
                print "istep 0"
            else:
                dbeta = min(p*dbeta, beta-beta0)
        else:
            istep += 1
            print "istep", istep
            ketMPO = ketMPOnew       
            beta0 += dbeta
            
            p = RK.adaptive_fix(p)

            dbeta = p*dbeta
            if dbeta > beta - beta0:
                dbeta = beta - beta0
                loop = False
            
        print "dbeta", dbeta
        out = tMPS(rk, ketMPO, HMPO, -0.5j*dbeta, ephtable, thresh=thresh,\
                cleanexciton=1, compress_method=compress_method, QNargs=QNargs,\
                approxeiHt=approxeiHpt, normalize=normalize)
        if rk.adaptive == True:
            ketMPOnew, p  = out
            print "p=",p
        else:
            ketMPOnew = out
            p = 1.0

    return ketMPOnew


def random_MPS(mol, pbond, M):
    '''
    random entangled MPS
    '''
    MPSdim = [1] + [M] * (len(pbond)-1) + [1]
    MPS = []
    for imps in xrange(len(pbond)):
        mps = np.random.random([MPSdim[imps],pbond[imps],MPSdim[imps+1]])-0.5
        MPS.append(mps)
    return MPS, MPSdim


def Max_Entangled_MPS(mol, pbond):
    '''
    sum of Identity operator / not normalized 
    '''

    MPSdim = [1] * (len(pbond)+1)

    MPS = []
    for imps in xrange(len(pbond)):
        mps = np.ones([MPSdim[imps],pbond[imps],MPSdim[imps+1]])
        MPS.append(mps)

    return MPS, MPSdim


def Max_Entangled_GS_MPS(mol, pbond, norm=True, QNargs=None):
    '''
    T = \infty maximum entangled GS state
    electronic site: pbond 0 element 1.0
                     pbond 1 element 0.0
    phonon site: digonal element sqrt(pbond) for normalization
    '''
    MPSdim = [1] * (len(pbond)+1)
    MPSQN = [[0]] * (len(pbond)+1)
    MPSQNidx = len(pbond)-1
    MPSQNtot = 0

    MPS = []
    imps = 0
    for imol in xrange(len(mol)):
        mps = np.zeros([MPSdim[imps],pbond[imps],MPSdim[imps+1]])
        for ibra in xrange(pbond[imps]):
            if ibra == 0:
                mps[0,ibra,0] = 1.0
            else:
                mps[0,ibra,0] = 0.0


        MPS.append(mps)
        imps += 1

        for iph in xrange(mol[imol].nphs):
            for iboson in xrange(mol[imol].ph[iph].nqboson):
                mps = np.zeros([MPSdim[imps],pbond[imps],MPSdim[imps+1]])
                if norm == True:
                    mps[0,:,0] = 1.0/np.sqrt(pbond[imps])
                else:
                    mps[0,:,0] = 1.0
                
                MPS.append(mps)
                imps += 1
    
    if QNargs is None:
        return MPS, MPSdim
    else:
        return [MPS, MPSQN, MPSQNidx, MPSQNtot], MPSdim 


def hilbert_to_liouville(MPS, QNargs=None):
    '''
    from hilbert MPS to Liouville MPO, the up and down physical bond is
    diagonal, for ancillary finite temperature propagation
    '''
    if QNargs is not None:
        MPSmat = MPS[0]
    else:
        MPSmat = MPS

    MPO = []
    for imps in MPSmat:
        mpo = np.zeros([imps.shape[0]]+[imps.shape[1]]*2+[imps.shape[2]],dtype=imps.dtype)
        for iaxis in xrange(imps.shape[1]):
            mpo[:,iaxis,iaxis,:] = imps[:,iaxis,:].copy()
        MPO.append(mpo)
    
    if QNargs is not None:
        MPO = [MPO] + copy.deepcopy(MPS[1:])

    return MPO


def Max_Entangled_EX_MPO(mol, pbond, norm=True, QNargs=None):
    '''
    T = \infty maximum entangled EX state
    '''
    MPS, MPSdim = Max_Entangled_GS_MPS(mol, pbond, norm=norm, QNargs=QNargs)

    # the creation operator \sum_i a^\dagger_i
    creationMPO, creationMPOdim = MPSsolver.construct_onsiteMPO(mol, pbond, "a^\dagger",
            QNargs=QNargs)

    EXMPS =  mpslib.mapply(creationMPO, MPS, QNargs=QNargs)
    if norm == True:
        EXMPS = mpslib.scale(EXMPS, 1.0/np.sqrt(float(len(mol))), QNargs=QNargs) # normalize
    
    MPOdim = creationMPOdim
    MPO = hilbert_to_liouville(EXMPS, QNargs=QNargs)
    
    return MPO, MPOdim 


def MPOprop(iMPS, HMPO, nsteps, dt, ephtable, thresh=0, cleanexciton=None):
    '''
        In principle, We can directly do MPO propagation and then trace it do
        get the correlation function. But it seems that the bond dimension
        increase much faster than propgation based on MPS. (Maybe DMRG is
        suited for wavefunction not operator)
        If this works, then every dynamic correlation function is solved if
        e^{iHt} is known. So, this may not work.

        ###
        doesn't work based on some simple test
    '''
    #for istep in xrange(1,nsteps):
    #    iMPS = tMPS(iMPS, HMPO, dt, ephtable, thresh=thresh, cleanexciton=cleanexciton)


def dynamics_TDDMRG(setup, mol, J, HMPO, MPS, stop, dt, ephtable, thresh=0.,\
        cleanexciton=None, scheme="P&C", QNargs=None, property_MPOs=[]):
    
    '''
    ZT/FT dynamics to calculate the expectation value of a list of MPOs
    the MPOs is only related to the MPS part (usually electronic part)
    '''
    if type(stop) == int:
        nsteps = stop
        tstop = dt * nsteps
    elif type(stop) == float:
        tstop= stop
        nsteps = 100000

    factor = mpslib.norm(MPS, QNargs=QNargs)
    print "factor",factor
    MPS = mpslib.scale(MPS, 1./factor, QNargs=QNargs)

    data = [[] for i in xrange(len(property_MPOs))]
    tlist = []
    t = 0. 

    for istep in range(nsteps):
        print "istep", istep
        if istep != 0:
            
            MPS = tMPS(setup.rk, MPS, HMPO, dt, ephtable, thresh=thresh, \
                    cleanexciton=cleanexciton, compress_method="svd",
                    QNargs=QNargs, normalize=1.0, scheme=scheme)
            
            t += dt
            
            if setup.rk.adaptive == True:
                MPS, p = MPS
                p = RK.adaptive_fix(p)
                dt = p*dt
                print "p=", p, dt

        tlist.append(t)
        # calculate the expectation value
        for iMPO, MPO in enumerate(property_MPOs):
            ft = mpslib.exp_value(MPS, MPO, MPS, QNargs=QNargs) * factor**2
            data[iMPO].append(ft)
        
        wfn_store(MPS, istep, "MPS.pkl")
        wfn_store(tlist, istep, "tlist.pkl")
        autocorr_store(data, istep)

        if t > tstop:
            break
    
    return tlist, data
    
