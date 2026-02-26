import streamlit as st
import pandas as pd
import math
from datetime import date, timedelta

# ==========================================
# 0. 全局配置与虚拟数据库初始化
# ==========================================
st.set_page_config(page_title="手搓跟单系统(全量版)", page_icon="🏭", layout="wide", initial_sidebar_state="expanded")

# --- 基础数据域 ---
if 'materials' not in st.session_state:
    st.session_state.materials = pd.DataFrame({
        "物料编码": ["MAT-001", "MAT-002", "MAT-003", "MAT-004"],
        "物料名称": ["阻燃外壳", "纯铜插针", "控制芯片", "包装彩盒"],
        "采购周期(天)": [3, 5, 7, 2],
        "最小采购量": [1000, 5000, 500, 1000] # 采购基本单位
    })

if 'inventory' not in st.session_state:
    st.session_state.inventory = pd.DataFrame({
        "物料编码": ["MAT-001", "MAT-002", "MAT-003", "MAT-004"],
        "现存量": [5000, 10000, 200, 1000],
        "预留量": [0, 0, 0, 0],
        "安全库存": [500, 1000, 100, 200]
    })

# BOM 结构 (字典模拟)
BOM_MASTER = {
    "漏电保护插头-标准款": {"MAT-001": 1, "MAT-002": 3, "MAT-003": 1, "MAT-004": 1},
    "精密冲压端子-B型": {"MAT-002": 1, "MAT-004": 0.1} 
}

if 'products' not in st.session_state:
    st.session_state.products = pd.DataFrame({
        "产品规格": ["漏电保护插头-标准款", "精密冲压端子-B型"],
        "标准日产能": [200, 1000],  
        "包装缓冲天数": [1, 1]       
    })

# --- 业务单据域 ---
if 'orders' not in st.session_state:
    st.session_state.orders = pd.DataFrame({
        "订单编号": ["ORD-202310-001"],
        "客户名称": ["华东科技集团"],
        "产品规格": ["漏电保护插头-标准款"],
        "订单数量": [1000],
        "已完工数": [0],
        "承诺交期": [date.today() + timedelta(days=10)],
        "预计发货日": [date.today() + timedelta(days=15)], 
        "最晚到料日": [date.today() + timedelta(days=5)],
        "收款情况": ["未收款"],
        "异常说明": ["无"], 
        "当前状态": ["备料中"], # 状态机：新建 → 备料中 → 可生产 → 生产中 → 待出货 → 已出货
        "物流公司": [""],
        "物流运单": [""]
    })

if 'purchases' not in st.session_state:
    st.session_state.purchases = pd.DataFrame(columns=["采购单号", "关联订单", "物料编码", "采购数量", "承诺到货日", "实际到货日", "状态"])

# ==========================================
# 辅助计算函数 (核心大脑)
# ==========================================
def run_mrp(order_id):
    """MRP 算缺料逻辑"""
    order = st.session_state.orders[st.session_state.orders["订单编号"] == order_id].iloc[0]
    bom = BOM_MASTER.get(order["产品规格"], {})
    shortages = []
    latest_arrival = date.today()
    
    for mat_code, unit_qty in bom.items():
        req_qty = order["订单数量"] * unit_qty 
        inv_row = st.session_state.inventory[st.session_state.inventory["物料编码"] == mat_code].iloc[0]
        avail_qty = inv_row["现存量"] - inv_row["预留量"] - inv_row["安全库存"] 
        shortage = max(0, req_qty - avail_qty) 
        
        if shortage > 0:
            mat_info = st.session_state.materials[st.session_state.materials["物料编码"] == mat_code].iloc[0]
            po_qty = max(shortage, mat_info["最小采购量"])
            arrival_date = date.today() + timedelta(days=int(mat_info["采购周期(天)"])) 
            
            if arrival_date > latest_arrival:
                latest_arrival = arrival_date
                
            shortages.append({
                "关联订单": order_id, "物料编码": mat_code, "采购数量": po_qty, 
                "承诺到货日": arrival_date, "实际到货日": None, "状态": "采购中"
            })
            
            idx = st.session_state.inventory.index[st.session_state.inventory["物料编码"] == mat_code].tolist()[0]
            st.session_state.inventory.at[idx, "预留量"] += avail_qty 
        else:
            idx = st.session_state.inventory.index[st.session_state.inventory["物料编码"] == mat_code].tolist()[0]
            st.session_state.inventory.at[idx, "预留量"] += req_qty
            
    if shortages:
        for s in shortages:
            s["采购单号"] = f"PO-{date.today().strftime('%m%d')}-{len(st.session_state.purchases)+1:03d}"
            st.session_state.purchases = pd.concat([st.session_state.purchases, pd.DataFrame([s])], ignore_index=True)
        return "缺料", latest_arrival
    return "齐套", date.today()

def calc_eta(product_name, remaining_qty, start_date):
    """ETA 推算逻辑"""
    if remaining_qty <= 0: return date.today()
    prod_info = st.session_state.products[st.session_state.products["产品规格"] == product_name].iloc[0]
    prod_days = math.ceil(remaining_qty / prod_info["标准日产能"]) 
    return start_date + timedelta(days=prod_days + int(prod_info["包装缓冲天数"])) 

# ==========================================
# 系统 UI 与 菜单
# ==========================================
menu = st.sidebar.radio("核心业务域", ["1. 首页看板", "2. 销售与订单", "3. 计划与采购", "4. 仓储物流", "5. 生产车间", "⚙️ 基础数据"])

# --- 1. 首页看板 ---
if menu == "1. 首页看板":
    st.header("📊 管理驾驶舱 (总览看板)")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("待处理新订单", len(st.session_state.orders[st.session_state.orders["当前状态"] == "新建"]))
    col2.metric("缺料/备料中", len(st.session_state.orders[st.session_state.orders["当前状态"] == "备料中"]))
    col3.metric("在制异常", len(st.session_state.orders[st.session_state.orders["异常说明"] != "无"]))
    col4.metric("待发货", len(st.session_state.orders[st.session_state.orders["当前状态"] == "待出货"]))
    
    st.subheader("🚨 预警中心") 
    risk_col1, risk_col2 = st.columns(2)
    
    with risk_col1:
        st.error("**到料超期预警**") 
        overdue_pos = st.session_state.purchases[(st.session_state.purchases["承诺到货日"] < date.today()) & (st.session_state.purchases["状态"] == "采购中")]
        if not overdue_pos.empty:
            st.dataframe(overdue_pos)
        else:
            st.success("暂无超期未到料采购单")
            
    with risk_col2:
        st.warning("**交期风险预警 (预计发货晚于客户要求)**") 
        risk_orders = st.session_state.orders[(st.session_state.orders["预计发货日"].notna()) & (st.session_state.orders["预计发货日"] > st.session_state.orders["承诺交期"])]
        if not risk_orders.empty:
            st.dataframe(risk_orders[["订单编号", "客户名称", "承诺交期", "预计发货日"]])
        else:
            st.success("暂无交期延误风险订单")

# --- 2. 销售与订单 ---
elif menu == "2. 销售与订单":
    st.header("销售域：订单录入与详情追踪")
    
    tab1, tab2, tab3 = st.tabs(["📝 录入新订单", "📋 订单总表(含ETA)", "🔍 订单详情(一页到底)"])
    
    with tab1:
        with st.form("new_order"):
            c1, c2 = st.columns(2)
            cstm = c1.text_input("客户名称")
            prod = c1.selectbox("产品规格", st.session_state.products["产品规格"])
            qty = c2.number_input("数量", min_value=1, step=100)
            ddl = c2.date_input("交期要求")
            if st.form_submit_button("提交订单", type="primary"):
                oid = f"ORD-{date.today().strftime('%m%d')}-{len(st.session_state.orders)+1:03d}" 
                new_row = pd.DataFrame([{"订单编号": oid, "客户名称": cstm, "产品规格": prod, "订单数量": qty, "已完工数": 0, "承诺交期": ddl, "预计发货日": None, "最晚到料日": None, "收款情况": "未收款", "异常说明": "无", "当前状态": "新建", "物流公司": "", "物流运单": ""}])
                st.session_state.orders = pd.concat([st.session_state.orders, new_row], ignore_index=True)
                st.success(f"订单 {oid} 创建成功！")

    with tab2:
        st.subheader("全量订单台账监控")
        df_display = st.session_state.orders.copy()
        
        def check_risk(row):
            if pd.isna(row["预计发货日"]) or row["当前状态"] in ["待出货", "已出货"]: return "🟢 正常"
            if row["预计发货日"] > row["承诺交期"]: return "🔴 延期风险"
            return "🟢 正常"
            
        df_display["交付风险"] = df_display.apply(check_risk, axis=1)
        cols = ["订单编号", "客户名称", "产品规格", "订单数量", "承诺交期", "预计发货日", "交付风险", "当前状态", "异常说明"]
        st.dataframe(df_display[cols], use_container_width=True)

    with tab3: 
        sel_order = st.selectbox("搜索/选择订单", st.session_state.orders["订单编号"])
        if sel_order:
            order_data = st.session_state.orders[st.session_state.orders["订单编号"] == sel_order].iloc[0]
            
            dt1, dt2, dt3, dt4 = st.tabs(["1. 基本信息", "2. 备料情况", "3. 生产进度", "4. 出货信息"])
            
            with dt1: 
                st.write(f"**客户:** {order_data['客户名称']} | **状态:** {order_data['当前状态']} | **收款:** {order_data['收款情况']}")
                st.write(f"**产品:** {order_data['产品规格']} | **数量:** {order_data['订单数量']} | **承诺交期:** {order_data['承诺交期']}")
                if st.button("标记为已收款"):
                    idx = st.session_state.orders.index[st.session_state.orders["订单编号"] == sel_order].tolist()[0]
                    st.session_state.orders.at[idx, "收款情况"] = "已收款"
                    st.rerun()

            with dt2: 
                st.write(f"**最晚到料日:** {order_data['最晚到料日']}")
                pos = st.session_state.purchases[st.session_state.purchases["关联订单"] == sel_order]
                if not pos.empty: st.dataframe(pos[["采购单号", "物料编码", "采购数量", "承诺到货日", "状态"]])
                else: st.info("暂未生成采购单")
                
            with dt3: 
                st.progress(order_data['已完工数'] / order_data['订单数量'] if order_data['订单数量']>0 else 0)
                st.write(f"进度: {order_data['已完工数']} / {order_data['订单数量']} | 异常记录: {order_data['异常说明']}")
                st.write(f"**系统测算 ETA (预计发货日):** {order_data['预计发货日']}")
                
            with dt4: 
                st.write(f"物流公司: {order_data['物流公司']} | 运单号: {order_data['物流运单']}")

# --- 3. 计划与采购 ---
elif menu == "3. 计划与采购":
    st.header("PMC计划与采购协同")
    
    tab1, tab2 = st.tabs(["🧩 拆BOM与算缺料", "🛒 采购到料跟进"])
    
    with tab1: 
        new_orders = st.session_state.orders[st.session_state.orders["当前状态"] == "新建"]
        if not new_orders.empty:
            sel_mrp = st.selectbox("选择订单运行 MRP 计算", new_orders["订单编号"])
            if st.button("执行计算 (生成采购单并排产)", type="primary"):
                status, latest_arr = run_mrp(sel_mrp)
                idx = st.session_state.orders.index[st.session_state.orders["订单编号"] == sel_mrp].tolist()[0]
                
                prod = st.session_state.orders.at[idx, "产品规格"]
                qty = st.session_state.orders.at[idx, "订单数量"]
                start_date = latest_arr + timedelta(days=1)
                eta = calc_eta(prod, qty, start_date)
                
                st.session_state.orders.at[idx, "最晚到料日"] = latest_arr
                st.session_state.orders.at[idx, "预计发货日"] = eta
                st.session_state.orders.at[idx, "当前状态"] = "可生产" if status == "齐套" else "备料中"
                
                st.success(f"计算完成！物料：{status}。最晚到料日：{latest_arr}，推算 ETA：{eta}")
                st.rerun()
        else:
            st.info("无待算订单")
            
    with tab2: 
        po_df = st.session_state.purchases
        st.dataframe(po_df)
        if not po_df.empty:
            po_id = st.selectbox("选择采购单更新状态", po_df[po_df["状态"]=="采购中"]["采购单号"])
            if st.button("标记已到料入库"):
                idx = po_df.index[po_df["采购单号"] == po_id].tolist()[0]
                st.session_state.purchases.at[idx, "实际到货日"] = date.today()
                st.session_state.purchases.at[idx, "状态"] = "已入库"
                
                mat = st.session_state.purchases.at[idx, "物料编码"]
                qty = st.session_state.purchases.at[idx, "采购数量"]
                inv_idx = st.session_state.inventory.index[st.session_state.inventory["物料编码"] == mat].tolist()[0]
                st.session_state.inventory.at[inv_idx, "现存量"] += qty
                st.success("到料成功，库存已增加！")

# --- 4. 仓储物流 ---
elif menu == "4. 仓储物流":
    st.header("仓库台账与物流出货")
    
    tab1, tab2 = st.tabs(["📦 库存台账", "🚚 发货登记"])
    with tab1: 
        inv_df = st.session_state.inventory.copy()
        inv_df["可用量"] = inv_df["现存量"] - inv_df["预留量"] - inv_df["安全库存"] 
        st.dataframe(inv_df, use_container_width=True)
        
    with tab2: 
        ship_orders = st.session_state.orders[st.session_state.orders["当前状态"] == "待出货"]
        if not ship_orders.empty:
            ship_id = st.selectbox("选择待发货订单", ship_orders["订单编号"])
            logistics = st.text_input("物流公司")
            tracking = st.text_input("运单号") 
            if st.button("确认发货"):
                idx = st.session_state.orders.index[st.session_state.orders["订单编号"] == ship_id].tolist()[0]
                st.session_state.orders.at[idx, "物流公司"] = logistics
                st.session_state.orders.at[idx, "物流运单"] = tracking
                st.session_state.orders.at[idx, "当前状态"] = "已出货" 
                st.success("发货登记成功！")
                st.rerun()
        else:
            st.info("暂无待发货订单")

# --- 5. 生产车间 ---
elif menu == "5. 生产车间":
    st.header("车间生产报工与异常记录") 
    
    prod_orders = st.session_state.orders[st.session_state.orders["当前状态"].isin(["可生产", "生产中"])]
    if not prod_orders.empty:
        sel_prod = st.selectbox("选择工单", prod_orders["订单编号"])
        order_info = prod_orders[prod_orders["订单编号"] == sel_prod].iloc[0]
        
        st.write(f"当前进度: {order_info['已完工数']} / {order_info['订单数量']}")
        with st.form("prod_report"):
            add_qty = st.number_input("今日合格产出", min_value=0, step=10) 
            abnormal = st.selectbox("异常提报", ["无", "停机", "缺料", "设备故障", "质量异常"]) 
            
            if st.form_submit_button("提交报工", type="primary"):
                idx = st.session_state.orders.index[st.session_state.orders["订单编号"] == sel_prod].tolist()[0]
                new_qty = order_info['已完工数'] + add_qty
                
                st.session_state.orders.at[idx, "已完工数"] = new_qty
                st.session_state.orders.at[idx, "异常说明"] = abnormal
                st.session_state.orders.at[idx, "当前状态"] = "生产中"
                
                if new_qty >= order_info['订单数量']:
                    st.session_state.orders.at[idx, "当前状态"] = "待出货" 
                    st.success("工单已完工，已流转至物流待出货！")
                else:
                    new_eta = calc_eta(order_info['产品规格'], order_info['订单数量'] - new_qty, date.today())
                    st.session_state.orders.at[idx, "预计发货日"] = new_eta
                    st.success("报工成功，ETA已动态更新！")
                st.rerun()
    else:
        st.info("车间暂无任务")

# --- 6. 基础数据 ---
elif menu == "⚙️ 基础数据":
    st.header("产品档案与产能基准")
    edited_df = st.data_editor(st.session_state.products, num_rows="dynamic", use_container_width=True)
    if st.button("保存基础数据变更", type="primary"):
        st.session_state.products = edited_df
        st.success("产能基准已更新！")
