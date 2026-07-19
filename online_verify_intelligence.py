"""
竞品情报引擎 - 线上验证脚本
验证5个工具在服务器上是否正常注册
"""
import httpx
import json
import sys

SERVER = "http://120.26.176.215:8420"

def verify_tools_registered():
    """验证工具是否注册到agent_loop"""
    print("=" * 60)
    print("竞品情报引擎 - 线上验证")
    print("=" * 60)
    
    try:
        # 1. 检查工具列表
        print("\n[1] 检查工具注册列表...")
        resp = httpx.get(f"{SERVER}/api/tools", timeout=10)
        if resp.status_code == 200:
            tools = resp.json()
            print(f"✓ 工具列表获取成功，共 {len(tools)} 个工具")
            
            # 检查5个新工具是否都在
            expected = [
                "map_competitor_sku",
                "compare_price_matrix", 
                "reverse_engineer_strategy",
                "generate_counter_strategy",
                "detect_market_gap"
            ]
            
            found = []
            for name in expected:
                if any(t.get("name") == name for t in tools):
                    found.append(name)
                    print(f"  ✓ {name}")
                else:
                    print(f"  ✗ {name} (未找到)")
            
            if len(found) == 5:
                print("\n✓ 所有5个竞品情报工具已成功注册")
                return True
            else:
                print(f"\n✗ 只找到 {len(found)}/5 个工具")
                return False
        else:
            print(f"✗ 获取工具列表失败: HTTP {resp.status_code}")
            return False
            
    except Exception as e:
        print(f"✗ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = verify_tools_registered()
    sys.exit(0 if success else 1)
