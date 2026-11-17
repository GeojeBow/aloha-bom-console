"""Headless run: scan, analyze, print a summary. Used for testing without the GUI."""
import collections
import pickle
import sys
import time

from bom_master.analyzer import analyze
from bom_master.config import Config, cache_dir
from bom_master.scanner import discover, load_all


def main():
    cfg = Config.load()
    t0 = time.time()
    files, others, errs = discover(cfg, progress=lambda m: print("  ", m, flush=True))
    t1 = time.time()
    print(f"discover: {len(files)} BOM files, {len(others)} other xlsx, {len(errs)} errors in {t1 - t0:.0f}s")
    last = [0]

    def prog(msg, done=None, total=None):
        if total and (done - last[0] >= 100 or done == total):
            last[0] = done
            print(f"   read {done}/{total}", flush=True)
    load_all(cfg, files, progress=prog)
    t2 = time.time()
    print(f"read: {t2 - t1:.0f}s")
    res = analyze(cfg, files, others, errs)
    print(f"analyze: {time.time() - t2:.1f}s")

    print("\nfiles by role/loc:", collections.Counter((f.role, f.loc) for f in files).most_common())
    print("files by ship:", collections.Counter((f.role, f.ship) for f in files).most_common())
    print("keys:", len(res.keys), "master rows:", len(res.master))
    print("wp status:", collections.Counter((k.ship, k.wp_status) for k in res.keys.values()).most_common())
    print("cn status:", collections.Counter(k.cn_status for k in res.keys.values()).most_common())
    print("issues:", collections.Counter((i.sev, i.code) for i in res.issues).most_common())
    print("\nSample issues:")
    seen = collections.Counter()
    for i in res.issues:
        if seen[i.code] < 3:
            seen[i.code] += 1
            print(f"  [{i.sev}] {i.code} {i.key} {i.rev} :: {i.detail[:160]}")
    print("\nSTAGING / other loc samples:")
    for f in [f for f in files if f.loc == "STAGING"][:10]:
        print("  ", f.role, f.rel)
    print("\nscan errors:", errs[:10])
    print("\nnon-BOM xlsx samples:", *others[:40], sep="\n   ")
    with open(cache_dir() / "last_result.pkl", "wb") as fh:
        pickle.dump(res, fh)


if __name__ == "__main__":
    sys.exit(main())
