"""
Méthode listant les différents fonctions mathématiques pouvant servire à la modélisation d'une
courbe
"""

import numpy as np

def model_exp(x,c0,c1,c2,c3):

    return c0+c1*x-c2*np.exp(-(x)/c3)

def model_1st_order(x,a,tau,c,b):


    z=a*(1-np.exp(-(x+b)/tau))+c
    return z


def model_2nd_order(x, a,tau,theta,b):

    S=np.empty(len(x))
    z=a*(1+b*x)*(1-np.exp(-(x-theta)/tau))
    for i in range(len(x)):
        #attention vérifier, t[i] a été remplacé par x[i]
        #=> il faudrait plutôt charger l'index de la dataframe
        if x[i]<theta:
            S[i]=0
        else:
            S[i]=1
    return z


model = {   '1st_order' : model_1st_order,
            '2st_order' : model_2nd_order,
            'exp'       : model_exp,
            'polynomial': None}

model_thermique = { '1st_order' : model_1st_order,
                    '2nd_order' : model_2nd_order,
                    'exp'       : model_exp}