"""Search kick/snare placements to hit each level's target band center."""
import itertools
METRIC_WEIGHTS = {0:5,8:4,4:3,12:3,2:2,6:2,10:2,14:2,
                  1:1,3:1,5:1,7:1,9:1,11:1,13:1,15:1}
N = 16
SALIENCE = {"kick": 2.0, "snare": 1.5}


def index_2bar(kick, snare):
    union = set()
    sal = {}
    for s in kick:
        for b in (0,1):
            p=b*N+s; union.add(p); sal[p]=max(sal.get(p,0),SALIENCE["kick"])
    for s in snare:
        for b in (0,1):
            p=b*N+s; union.add(p); sal[p]=max(sal.get(p,0),SALIENCE["snare"])
    if not union: return 0.0
    total=2*N; score=0.0
    for s in sorted(union):
        w=METRIC_WEIGHTS[s%N]; best=0
        for d in range(1,total):
            pos=(s+d)%total
            if pos in union: break
            best=max(best,METRIC_WEIGHTS[pos%N])
        if best-w>0: score+=(best-w)*sal[s]
    return round(score,1)


targets = {"L1": (12,18), "L2": (26,34), "L3": (48,65)}
# fixed snare backbeat for L1/L2 (preserve beat salience); L3 may displace.
weak = [1,2,3,5,6,7,9,10,11,13,14,15]   # candidate weak kick steps
strong = [0,4,8,12]

best_for = {}
# L1 light: keep downbeat (beat 1) for salience, allow beat 3 anticipated,
# 1-2 weak pushes, snare backbeat.
for keep in ([0],[0,8]):
    for r in (1,2):
        for combo in itertools.combinations(weak, r):
            k = sorted(set(keep)|set(combo))
            idx = index_2bar(k,[4,12])
            if 13<=idx<=17:
                best_for.setdefault("L1",(idx,k,[4,12])); break
        if "L1" in best_for: break
    if "L1" in best_for: break
# L2 sweet spot ~30: leave one strong beat empty, 3-4 weak pushes, snare backbeat
for r in (3,4):
    for combo in itertools.combinations(weak, r):
        for keep in ([0],[8],[0,8],[]):
            k=sorted(set(keep)|set(combo))
            idx=index_2bar(k,[4,12])
            if 28<=idx<=32:
                best_for.setdefault("L2",(idx,k,[4,12])); break
        if "L2" in best_for: break
    if "L2" in best_for: break
# L3 heavy ~55: strong beats empty, many weak kicks, displaced snare
for r in (4,5,6):
    for combo in itertools.combinations(weak, r):
        for sn in ([5,13],[5,11],[3,13]):
            idx=index_2bar(list(combo),sn)
            if 48<=idx<=65:
                best_for.setdefault("L3",(idx,sorted(combo),sn)); break
        if "L3" in best_for: break
    if "L3" in best_for: break

for lvl in ("L1","L2","L3"):
    if lvl in best_for:
        idx,k,sn = best_for[lvl]
        print(f"{lvl}: idx={idx}  kick={k} snare={sn}  target {targets[lvl]}")
    else:
        print(f"{lvl}: NO SOLUTION in band")
print("L0: idx=", index_2bar([0,8],[4,12]), " kick=[0,8] snare=[4,12]")
