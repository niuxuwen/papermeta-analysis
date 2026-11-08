from __future__ import annotations

import math

def sigmoid(x):
    if x >= 0:
        return 1/(1+math.exp(-x))
    e = math.exp(x)
    return e/(1+e)

def components(names,edges):
    adjacency = {n:set() for n in names}
    for a,b,_,_ in edges:
        adjacency[a].add(b)
        adjacency[b].add(a)
    result,seen = [],set()
    for start in sorted(names):
        if start in seen:
            continue
        pending,found = [start],set()
        seen.add(start)
        while pending:
            node = pending.pop()
            found.add(node)
            for other in sorted(adjacency[node]-seen):
                seen.add(other)
                pending.append(other)
        result.append(sorted(found))
    return result

def _solve(diagonal,curvature,rhs):
    def multiply(vector):
        out = [d*x for d,x in zip(diagonal,vector)]
        for a,b,v in curvature:
            delta = v*(vector[a]-vector[b])
            out[a] += delta
            out[b] -= delta
        return out
    jacobi = list(diagonal)
    for a,b,v in curvature:
        jacobi[a] += v
        jacobi[b] += v
    x,r = [0.0]*len(rhs),list(rhs)
    direction = [v/d for v,d in zip(r,jacobi)]
    product = math.fsum(a*b for a,b in zip(r,direction))
    for _ in range(max(40,len(rhs)*2)):
        if product < 1e-22:
            break
        h = multiply(direction)
        step = product/math.fsum(a*b for a,b in zip(direction,h))
        x = [v+step*p for v,p in zip(x,direction)]
        r = [v-step*p for v,p in zip(r,h)]
        z = [v/d for v,d in zip(r,jacobi)]
        updated = math.fsum(a*b for a,b in zip(r,z))
        if updated < 1e-22:
            break
        direction = [v+(updated/product)*p for v,p in zip(z,direction)]
        product = updated
    if max((abs(a-b) for a,b in zip(multiply(x),rhs)),default=0)>1e-6:
        raise ArithmeticError('Uncertainty solve did not converge')
    return x
