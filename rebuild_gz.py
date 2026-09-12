# -*- coding: utf-8 -*-
"""
重建所有 .gz 数据包
背景: 每日更新只重写了未压缩的 .js, 忘记重新 gzip;
      而 HTML 加载器优先加载 .gz (DecompressionStream), 导致线上一直读到上一交易日的数据包。
用法: python rebuild_gz.py [--targets dir1 dir2 ...]
"""
import gzip
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))

# 需要打包的数据文件(不含 echarts.min.js, 内容固定不变)
PACK = [
    "strong_data.js",
    "buydian_v21_data.js",
    "kline_ref.js",
    "year_kline.js",
    "gain_board.js",
    "sector_ref.js",
]


def gz_one(args):
    src, level = args
    dst = src + ".gz"
    tmp = dst + ".tmp"
    t0 = time.time()
    with open(src, "rb") as fin, gzip.open(tmp, "wb", compresslevel=level) as fout:
        shutil.copyfileobj(fin, fout, 4 << 20)
    os.replace(tmp, dst)          # 原子替换, 避免中途被读到半个包
    return (os.path.basename(src),
            os.path.getsize(src),
            os.path.getsize(dst),
            time.time() - t0)


def build_dir(root, level=9):
    jobs = []
    for name in PACK:
        src = os.path.join(root, name)
        if os.path.exists(src):
            jobs.append((src, level))
        else:
            print(f"  [skip] {root}/{name} 不存在", flush=True)
    if not jobs:
        return
    print(f"=== {root}  待打包 {len(jobs)} 个 ===", flush=True)
    with ProcessPoolExecutor(max_workers=min(5, len(jobs))) as ex:
        for name, sz_in, sz_out, sec in ex.map(gz_one, jobs):
            print(f"  {name:28s} {sz_in/1048576:8.2f} MB -> {sz_out/1048576:7.2f} MB "
                  f"({sz_in/max(sz_out,1):.2f}x) {sec:5.1f}s", flush=True)


def main():
    args = sys.argv[1:]
    if "--targets" in args:
        i = args.index("--targets")
        roots = args[i + 1:] or [BASE]
    else:
        roots = [BASE]
    roots = [r if os.path.isabs(r) else os.path.join(BASE, r) for r in roots]
    t0 = time.time()
    for r in roots:
        build_dir(r)
    print(f"ALL DONE  elapsed {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
