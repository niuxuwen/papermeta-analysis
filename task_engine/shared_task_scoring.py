from __future__ import annotations

import math

from .paired_scoring import sigmoid, _solve

def _softplus(x):
    return x+math.log1p(math.exp(-x)) if x>=0 else math.log1p(math.exp(x))

def objective(theta,edges,priors):
    return math.fsum(w*(_softplus(theta[a]-theta[b])-y*(theta[a]-theta[b])) for a,b,y,w in edges) + math.fsum(
        p*(_softplus(t)-.5*t) for p,t in zip(priors,theta) if p)

def fit_graph(layout, *, tolerance=1e-9, max_iterations=60):
    """Damped Newton/PCG fit; stdlib only, no server dependency additions."""
    edges,priors=layout['edges'],layout['priors'];theta=[0.]*len(priors)
    if not theta:return [],dict(converged=True,iterations=0,max_gradient=0.,solver='NEWTON_PCG')
    error=float('inf')
    quadratic=layout.get('quadratic_edges',[])
    def loss(v):
        return objective(v,edges,priors)+.5*math.fsum(w*max(0.,m-v[a]+v[b])**2 for a,b,m,w in quadratic)
    for iteration in range(1,max_iterations+1):
        gradient=[p*(sigmoid(t)-.5) for p,t in zip(priors,theta)]
        diagonal=[p*sigmoid(t)*(1-sigmoid(t)) for p,t in zip(priors,theta)]
        curvature=[]
        for a,b,y,w in edges:
            prob=sigmoid(theta[a]-theta[b]);d=w*(prob-y)
            gradient[a]+=d;gradient[b]-=d;curvature.append((a,b,w*prob*(1-prob)))
        for a,b,m,w in quadratic:
            residual=m-theta[a]+theta[b]
            if residual>0:
                gradient[a]-=w*residual;gradient[b]+=w*residual;curvature.append((a,b,w))
        error=max(map(abs,gradient))
        if error<tolerance:break
        step=_solve(diagonal,curvature,gradient)
        current=loss(theta);descent=math.fsum(a*b for a,b in zip(gradient,step))
        rate=1.
        while rate>=2**-30:
            updated=[t-rate*s for t,s in zip(theta,step)]
            if loss(updated)<=current-1e-4*rate*descent+1e-12:
                theta=updated;break
            rate/=2
        else:raise ArithmeticError('Shared-task fit line search failed')
    return theta,dict(converged=error<1e-7,iterations=iteration,max_gradient=error,
        solver='NEWTON_PCG_SQUARED_HINGE' if quadratic else 'NEWTON_PCG',regularization_terms=len(quadratic))
