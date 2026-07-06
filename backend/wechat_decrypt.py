#!/usr/bin/env python3
"""
微信数据库解密工具 (支持新版 XWeChat/Weixin + 旧版 WeChat)
===========================================================
用法:
  python wechat_decrypt.py                     # 自动检测并解密所有消息
  python wechat_decrypt.py --key HEX_KEY       # 手动提供密钥(64位hex)
  python wechat_decrypt.py --bruteforce        # 暴力搜索密钥(可能很慢)
  python wechat_decrypt.py --list              # 仅列出数据库和表
  python wechat_decrypt.py --table TABLE_NAME  # 解密指定表
  python wechat_decrypt.py --output OUTPUT_DIR # 指定输出目录

环境要求: pip install sqlcipher3 pymem psutil (Windows)
"""

import os
import sys
import struct
import argparse
import hashlib
import json
import math
import time
from pathlib import Path

# ============================================================
# 1. 微信检测模块
# ============================================================

def find_wechat_process():
    """检测微信进程和版本。返回 {'type','pid','exe'} 或 None"""
    import psutil
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            name = (proc.info['name'] or '').lower()
            if 'weixin' == name or 'weixin.exe' == name:
                return {'type': 'weixin', 'pid': proc.info['pid'], 'exe': proc.info['exe']}
            if 'wechat' == name or 'wechat.exe' == name:
                exe_path = proc.info['exe'] or ''
                parent_dir = os.path.dirname(exe_path)
                if os.path.exists(os.path.join(parent_dir, 'Weixin.dll')):
                    return {'type': 'weixin', 'pid': proc.info['pid'], 'exe': exe_path}
                return {'type': 'wechat', 'pid': proc.info['pid'], 'exe': exe_path}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def find_db_paths():
    """查找微信数据库路径。返回 [{'path','name','size','user','type'}]"""
    candidates = []

    # 新版微信 (XWeChat) → Documents\xwechat_files\wxid_xxx\db_storage\message\*.db
    xwechat_base = os.path.expandvars(r"%USERPROFILE%\Documents\xwechat_files")
    if os.path.isdir(xwechat_base):
        for user_dir in os.listdir(xwechat_base):
            user_path = os.path.join(xwechat_base, user_dir)
            if not os.path.isdir(user_path):
                continue
            for root, dirs, files in os.walk(user_path):
                for d in dirs:
                    if d.startswith('db_storage'):
                        msg_path = os.path.join(root, d, 'message')
                        if os.path.isdir(msg_path):
                            for f in os.listdir(msg_path):
                                if f.endswith('.db'):
                                    full = os.path.join(msg_path, f)
                                    candidates.append({
                                        'path': full, 'name': f,
                                        'size': os.path.getsize(full),
                                        'user': user_dir, 'type': 'weixin'
                                    })
                break

    # 旧版微信 → Documents\WeChat Files\wxid_xxx\Msg\Multi\MSG*.db
    wechat_base = os.path.expandvars(r"%USERPROFILE%\Documents\WeChat Files")
    if os.path.isdir(wechat_base):
        for user_dir in os.listdir(wechat_base):
            user_path = os.path.join(wechat_base, user_dir)
            if not os.path.isdir(user_path):
                continue
            multi_dir = os.path.join(user_path, 'Msg', 'Multi')
            if os.path.isdir(multi_dir):
                for f in os.listdir(multi_dir):
                    if f.endswith('.db'):
                        full = os.path.join(multi_dir, f)
                        candidates.append({
                            'path': full, 'name': f,
                            'size': os.path.getsize(full),
                            'user': user_dir, 'type': 'wechat'
                        })

    return candidates


# ============================================================
# 2. 密钥暴力搜索模块 (.data段 + 堆内存)
# ============================================================

def calc_entropy(data: bytes) -> float:
    """计算字节熵值 (bits per byte)"""
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    entropy = 0.0
    for c in counts:
        if c:
            p = c / n
            entropy -= p * math.log2(p)
    return entropy


def get_weixin_writable_segments():
    """获取 Weixin.dll 的可写内存段"""
    import pymem
    try:
        pm = pymem.Pymem("Weixin.exe")
    except Exception:
        return []
    for mod in pm.list_modules():
        if mod.name.lower() == 'weixin.dll':
            wx_dll = mod
            break
    else:
        return []

    base = wx_dll.lpBaseOfDll
    pe_header = pm.read_bytes(base, 4096)
    e_lfanew = struct.unpack_from('<I', pe_header, 0x3C)[0]
    coff = e_lfanew + 4
    num_sections = struct.unpack_from('<H', pe_header, coff + 2)[0]
    opt_hdr_size = struct.unpack_from('<H', pe_header, coff + 16)[0]
    sec_off = coff + 20 + opt_hdr_size

    segments = []
    for i in range(num_sections):
        off = sec_off + i * 40
        name = pe_header[off:off+8].rstrip(b'\x00').decode('ascii', errors='replace')
        vsize = struct.unpack_from('<I', pe_header, off + 8)[0]
        vrva = struct.unpack_from('<I', pe_header, off + 12)[0]
        flags = struct.unpack_from('<I', pe_header, off + 36)[0]
        if flags & 0x80000000:
            segments.append({'name': name, 'start': base + vrva, 'size': vsize})
    return segments


def brute_force_key_from_segments(db_path):
    """从 Weixin.dll 可写段暴力搜索密钥"""
    import pymem
    import sqlcipher3
    try:
        pm = pymem.Pymem("Weixin.exe")
    except Exception as e:
        print(f"  [×] 无法附加微信进程: {e}")
        return None

    segments = get_weixin_writable_segments()
    if not segments:
        print("  [×] 无法获取 Weixin.dll 可写段")
        return None

    total_size = sum(s['size'] for s in segments)
    print(f"  [*] 可写段: {len(segments)} 个, 共 {total_size/1024:.0f}KB")

    # 采集高熵候选
    candidates = []
    step = 8
    min_entropy = 5.0

    for seg in segments:
        if seg['size'] < 32:
            continue
        try:
            data = pm.read_bytes(seg['start'], seg['size'])
        except Exception:
            continue
        for i in range(0, seg['size'] - 32 + 1, step):
            candidate = data[i:i+32]
            if calc_entropy(candidate) >= min_entropy:
                candidates.append(candidate)

    print(f"  [*] 高熵候选: {len(candidates)} 个")
    if not candidates:
        return None

    # 去重
    candidates = list(set(candidates))
    print(f"  [*] 去重后: {len(candidates)} 个")

    # 验证
    print(f"  [*] 开始验证 (可能需要几分钟)...")
    for idx, key in enumerate(candidates):
        if idx % 300 == 0 and idx > 0:
            print(f"    进度: {idx}/{len(candidates)}")
        try:
            conn = sqlcipher3.connect(db_path)
            conn.execute("PRAGMA cipher_compatibility = 4")
            conn.execute("PRAGMA key = ?", (key,))
            conn.execute("SELECT count(*) FROM sqlite_master")
            conn.close()
            print(f"\n  [✓] 找到密钥! (候选 #{idx})")
            print(f"       密钥(hex): {key.hex()}")
            return key
        except Exception:
            continue

    return None


def brute_force_key_from_heap(db_path, max_candidates=30000):
    """从堆内存搜索密钥（较慢但覆盖更全）"""
    import pymem
    import sqlcipher3
    import ctypes
    from ctypes import wintypes

    try:
        pm = pymem.Pymem("Weixin.exe")
    except Exception as e:
        print(f"  [×] 无法附加微信进程: {e}")
        return None

    kernel32 = ctypes.windll.kernel32

    class MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_void_p),
            ("AllocationBase", ctypes.c_void_p),
            ("AllocationProtect", wintypes.DWORD),
            ("RegionSize", ctypes.c_size_t),
            ("State", wintypes.DWORD),
            ("Protect", wintypes.DWORD),
            ("Type", wintypes.DWORD),
        ]

    handle = pm.process_handle
    candidates = []
    min_entropy = 5.2
    step = 4
    addr = 0
    regions_checked = 0

    print(f"  [*] 扫描堆内存 (限制 {max_candidates} 候选)...")

    while addr < 0x7FFFFFFFFFFF:
        mbi = MEMORY_BASIC_INFORMATION()
        result = kernel32.VirtualQueryEx(handle, ctypes.c_void_p(addr),
                                          ctypes.byref(mbi), ctypes.sizeof(mbi))
        if result == 0:
            break

        if (mbi.Type == 0x20000 and mbi.State == 0x1000 and
                (mbi.Protect & 0x04) and mbi.RegionSize >= 4096):
            regions_checked += 1
            region_size = min(mbi.RegionSize, 5 * 1024 * 1024)
            try:
                data = pm.read_bytes(mbi.BaseAddress, region_size)
            except Exception:
                addr += mbi.RegionSize
                continue

            for i in range(0, len(data) - 32 + 1, step):
                candidate = data[i:i+32]
                if candidate[0] in (0, 1, 0xFF) and candidate[0] == candidate[1]:
                    continue
                if calc_entropy(candidate) >= min_entropy:
                    candidates.append(candidate)
                    if len(candidates) >= max_candidates:
                        break
            if len(candidates) >= max_candidates:
                break

        addr += mbi.RegionSize

    # 去重
    candidates = list(set(candidates))
    print(f"  [*] 扫描 {regions_checked} 个堆区, 去重后 {len(candidates)} 候选")

    if not candidates:
        return None

    print(f"  [*] 验证候选密钥...")
    for idx, key in enumerate(candidates):
        if idx % 200 == 0 and idx > 0:
            print(f"    进度: {idx}/{len(candidates)}")
        try:
            conn = sqlcipher3.connect(db_path)
            conn.execute("PRAGMA cipher_compatibility = 4")
            conn.execute("PRAGMA key = ?", (key,))
            conn.execute("SELECT count(*) FROM sqlite_master")
            conn.close()
            print(f"\n  [✓] 找到密钥! (候选 #{idx})")
            print(f"       密钥(hex): {key.hex()}")
            return key
        except Exception:
            continue

    return None


# ============================================================
# 3. 解密模块
# ============================================================

def verify_key(db_path, key_bytes):
    """验证密钥是否正确"""
    import sqlcipher3
    try:
        conn = sqlcipher3.connect(db_path)
        conn.execute("PRAGMA cipher_compatibility = 4")
        conn.execute("PRAGMA key = ?", (key_bytes,))
        conn.execute("SELECT count(*) FROM sqlite_master")
        conn.close()
        return True
    except Exception:
        return False


def list_tables(db_path, key_bytes):
    """列出加密数据库中的表和列"""
    import sqlcipher3
    conn = sqlcipher3.connect(db_path)
    conn.execute("PRAGMA cipher_compatibility = 4")
    conn.execute("PRAGMA key = ?", (key_bytes,))
    cursor = conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table','view','index') ORDER BY type, name"
    )
    items = cursor.fetchall()
    columns_info = {}
    for name, _ in items:
        try:
            cols = conn.execute(f"PRAGMA table_info('{name}')").fetchall()
            columns_info[name] = [c[1] for c in cols]
        except Exception:
            columns_info[name] = []
    conn.close()
    return items, columns_info


def decrypt_table(db_path, key_bytes, table_name, output_path=None, fmt='json'):
    """解密指定表并导出"""
    import sqlcipher3
    conn = sqlcipher3.connect(db_path)
    conn.execute("PRAGMA cipher_compatibility = 4")
    conn.execute("PRAGMA key = ?", (key_bytes,))
    cols_cursor = conn.execute(f"PRAGMA table_info('{table_name}')")
    columns = [c[1] for c in cols_cursor.fetchall()]
    cursor = conn.execute(f"SELECT * FROM '{table_name}'")
    rows = cursor.fetchall()
    conn.close()

    if fmt == 'csv' and output_path:
        import csv
        with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for row in rows:
                writer.writerow([str(v) if not isinstance(v, bytes) else v.hex() for v in row])
        return len(rows)

    result = []
    for row in rows:
        record = {}
        for i, col in enumerate(columns):
            val = row[i]
            if isinstance(val, bytes):
                try:
                    val = val.decode('utf-8')
                except Exception:
                    val = val.hex()
            record[col] = val
        result.append(record)

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    return result


def decrypt_all_tables(db_path, key_bytes, output_dir):
    """解密全部表"""
    items, _ = list_tables(db_path, key_bytes)
    tables = [name for name, t in items if t == 'table']
    os.makedirs(output_dir, exist_ok=True)
    results = {}
    for table_name in tables:
        print(f"  [→] {table_name}...", end=' ', flush=True)
        try:
            path = os.path.join(output_dir, f"{table_name}.json")
            data = decrypt_table(db_path, key_bytes, table_name, path)
            print(f"✓ ({len(data) if isinstance(data, list) else data} 行)")
            results[table_name] = len(data) if isinstance(data, list) else data
        except Exception as e:
            print(f"✗ {e}")
            results[table_name] = f"ERROR: {e}"
    return results


# ============================================================
# 4. 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="微信(XWeChat/WeChat) 数据库解密工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python wechat_decrypt.py                          # 自动解密全部
  python wechat_decrypt.py --key abc...              # 手动密钥
  python wechat_decrypt.py --bruteforce              # 暴力搜索密钥
  python wechat_decrypt.py --list                    # 列出表
  python wechat_decrypt.py --table MSG --output ./out # 指定表+输出
        """
    )
    parser.add_argument('--key', type=str, help='64位十六进制密钥')
    parser.add_argument('--bruteforce', action='store_true', help='暴力搜索密钥')
    parser.add_argument('--list', action='store_true', help='仅列出表结构')
    parser.add_argument('--table', type=str, help='仅解密指定表')
    parser.add_argument('--output', type=str, default='./wechat_output', help='输出目录')
    parser.add_argument('--db-path', type=str, help='手动指定数据库路径')
    parser.add_argument('--csv', action='store_true', help='导出为CSV(默认JSON)')
    args = parser.parse_args()

    print("=" * 60)
    print("  微信数据库解密工具  v1.0")
    print("  支持: 新版 XWeChat/Weixin + 旧版 WeChat")
    print("=" * 60)

    # --- 查找数据库 ---
    if args.db_path:
        db_paths = [{'path': args.db_path, 'name': os.path.basename(args.db_path),
                      'size': os.path.getsize(args.db_path), 'user': 'manual', 'type': 'unknown'}]
    else:
        db_paths = find_db_paths()

    if not db_paths:
        print("\n[×] 未找到微信数据库!")
        print("    - 请确保微信已登录")
        print("    - 或使用 --db-path 手动指定路径")
        sys.exit(1)

    print(f"\n[*] 找到 {len(db_paths)} 个数据库:")
    for db in db_paths:
        print(f"    {db['name']:20s} {db['size']/1024/1024:7.1f}MB  [{db['type']}]")

    # 选择最大的消息数据库
    main_db = max(db_paths, key=lambda x: x['size'])
    db_path = main_db['path']
    print(f"\n[*] 目标: {main_db['name']} ({main_db['size']/1024/1024:.1f}MB)")

    # --- 获取密钥 ---
    key_bytes = None

    if args.key:
        try:
            key_bytes = bytes.fromhex(args.key)
            if len(key_bytes) != 32:
                print("[×] 密钥必须为64位十六进制 (32字节)")
                sys.exit(1)
            print(f"[*] 使用手动密钥: {args.key[:16]}...")
        except ValueError:
            print("[×] 无效的十六进制密钥")
            sys.exit(1)

    elif args.bruteforce:
        proc = find_wechat_process()
        if not proc:
            print("[×] 未找到微信进程! 请先启动微信")
            sys.exit(1)
        print(f"\n[*] 进程: {proc['type']} (PID={proc['pid']})")
        if proc['type'] == 'wechat':
            print("[!] 旧版微信暂不支持暴力搜索，请用其他工具获取密钥")
            sys.exit(1)

        print("[*] 阶段1: 搜索 .data 段...")
        key_bytes = brute_force_key_from_segments(db_path)
        if not key_bytes:
            print("[*] 阶段2: 搜索堆内存...")
            key_bytes = brute_force_key_from_heap(db_path)

    if not key_bytes:
        print("\n" + "=" * 60)
        print("  [!] 未能自动提取密钥")
        print("  请使用其他工具获取密钥后，用 --key 参数指定：")
        print("    python wechat_decrypt.py --key YOUR_HEX_KEY_64_CHARS")
        print("=" * 60)
        sys.exit(2)

    # --- 验证密钥 ---
    print(f"\n[*] 验证密钥...")
    if not verify_key(db_path, key_bytes):
        print("[×] 密钥验证失败! 数据库无法解密")
        sys.exit(1)
    print("  [✓] 密钥有效!")

    # --- 列出或解密 ---
    if args.list:
        items, col_info = list_tables(db_path, key_bytes)
        print(f"\n[*] 数据库对象 ({len(items)} 个):")
        for name, t in items:
            cols = col_info.get(name, [])
            col_str = ', '.join(cols[:6])
            if len(cols) > 6:
                col_str += f'...(+{len(cols)-6})'
            print(f"    [{t:5s}] {name:30s} cols: {col_str}")

    elif args.table:
        ext = 'csv' if args.csv else 'json'
        out = os.path.join(args.output, f"{args.table}.{ext}")
        if args.csv:
            n = decrypt_table(db_path, key_bytes, args.table, out, fmt='csv')
        else:
            data = decrypt_table(db_path, key_bytes, args.table, out)
            n = len(data)
        print(f"\n[✓] 已导出: {out} ({n} 行)")

    else:
        print(f"\n[*] 解密全部表 → {args.output}/")
        results = decrypt_all_tables(db_path, key_bytes, args.output)
        print(f"\n[✓] 完成! {len(results)} 个表")
        for t, c in results.items():
            print(f"    {t}: {c}")

    print(f"\n[密钥] {key_bytes.hex()}")
    print("[*] 请妥善保管密钥!")


if __name__ == '__main__':
    main()