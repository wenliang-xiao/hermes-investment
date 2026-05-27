
import baostock as bs
import sys, os

KEYWORD_GROUPS = {
    "digital_twin": ["数字孪生", "数字仿真", "虚拟仿真", "三维仿真", "仿真平台", "虚拟现实", "VR", "AR"],
    "simulation_sw": ["仿真软件", "CAE", "EDA", "CAD", "PLM", "仿真系统", "模拟仿真", "工业软件"],
    "3d_vision": ["3D视觉", "三维视觉", "机器视觉", "计算机视觉", "激光雷达", "LiDAR", "点云", "图像传感器"],
    "ai_perception": ["传感器", "AI芯片", "深度学习", "边缘计算", "力矩传感器", "六维力", "IMU", "MEMS", "编码器"],
    "wu_yi": ["五一视界", "51WORLD", "五十一世界"],
}

GROUP_LABELS = {
    "digital_twin": "数字孪生(Digital Twin)",
    "simulation_sw": "仿真软件(Simulation SW)",
    "3d_vision": "3D视觉/感知(3D Vision)",
    "ai_perception": "AI+机器人感知层(AI Perception)",
    "wu_yi": "五一视界(51WORLD)相关",
}

lg = bs.login()
print(f"baostock login: {lg.error_code} {lg.error_msg}")

rs = bs.query_stock_basic()
all_stocks = []
while (rs.error_code == '0') & rs.next():
    row = rs.get_row_data()
    if len(row) >= 6 and row[4] == '1' and row[5] == '1':
        all_stocks.append((row[0], row[1]))

print(f"Total A-shares listed: {len(all_stocks)}")

for gkey, keywords in KEYWORD_GROUPS.items():
    matches = set()
    for code, name in all_stocks:
        for kw in keywords:
            if kw.lower() in name.lower():
                matches.add((code, name))
                break
    matches = sorted(matches, key=lambda x: x[0])
    print(f"\n{'='*60}")
    print(f"  {GROUP_LABELS[gkey]}")
    print(f"{'='*60}")
    if matches:
        for code, name in matches:
            market = "创业板" if code.startswith("30") else "科创板" if code.startswith("688") else "主板"
            print(f"    {code}  {name} [{market}]")
    else:
        print("    (无匹配)")

bs.logout()
print("\nDone")
