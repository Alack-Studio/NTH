import streamlit as st
import pandas as pd
from datetime import date, timedelta

# ==========================================
# 0. 页面配置与初始数据 (模拟数据库)
# ==========================================
st.set_page_config(page_title="手搓跟单系统", layout="wide")

# 初始化订单数据缓存
if 'orders' not in st.session_state:
    st.session_state.orders = pd.DataFrame({
        "订单号": ["ORD-20231024-001", "ORD-20231024-002"],
        "客户": ["张三科技", "李四贸易"],
        "产品": ["漏电保护插头A", "端子B"],
        "订单数量": [1000, 5000],
        "已完成数": [200, 0],
        "交期要求": [date.today() + timedelta(days=10), date.today() + timedelta(days=15)],
        "状态": ["生产中", "待备料"],
        "运单号": ["", ""]
    })

# ==========================================
# 1. 侧边栏导航
# ==========================================
st.sidebar.title("🗂️ 极简跟单系统")
menu = st.sidebar.radio(
    "功能模块", 
    ["1. 首页看板", "2. 订单录入 (销售)", "3. 备料缺料 (采购)", "4. 生产报工 (车间)", "5. 出货登记 (物流)"]
)

# ==========================================
# 2. 页面逻辑实现
# ==========================================

# --- 模块 1: 首页看板 ---
if menu == "1. 首页看板":
    st.header("📊 首页看板 (管理驾驶舱)")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总订单数", len(st.session_state.orders))
    col2.metric("待备料", len(st.session_state.orders[st.session_state.orders["状态"] == "待备料"]))
    col3.metric("生产中", len(st.session_state.orders[st.session_state.orders["状态"] == "生产中"]))
    col4.metric("已出货", len(st.session_state.orders[st.session_state.orders["状态"] == "已出货"]))
    
    st.subheader("订单总览详情") #
    st.dataframe(st.session_state.orders, use_container_width=True)

# --- 模块 2: 订单录入 ---
elif menu == "2. 订单录入 (销售)":
    st.header("📝 订单录入") #
    with st.form("new_order_form"):
        col1, col2 = st.columns(2)
        with col1:
            customer = st.text_input("客户简称")
            product = st.selectbox("选择产品", ["漏电保护插头A", "端子B", "定制产品C"])
        with col2:
            qty = st.number_input("订单数量", min_value=1, step=100)
            deadline = st.date_input("交期要求")
            
        submitted = st.form_submit_button("生成订单")
        if submitted:
            new_order_id = f"ORD-{date.today().strftime('%Y%m%d')}-{len(st.session_state.orders)+1:03d}"
            new_row = pd.DataFrame([{
                "订单号": new_order_id, "客户": customer, "产品": product,
                "订单数量": qty, "已完成数": 0, "交期要求": deadline,
                "状态": "待备料", "运单号": ""
            }])
            st.session_state.orders = pd.concat([st.session_state.orders, new_row], ignore_index=True)
            st.success(f"订单 {new_order_id} 录入成功！")

# --- 模块 3: 备料缺料 ---
elif menu == "3. 备料缺料 (采购)":
    st.header("📦 备料与缺料计算") #
    st.info("第一阶段：上传 BOM Excel 模板，手工维护到料日期。") #
    
    uploaded_file = st.file_uploader("上传 BOM 模板 (Excel)", type=["xlsx", "xls"])
    if uploaded_file:
        st.success("BOM 解析成功！(此处为演示)")
    
    st.subheader("待备料订单跟进")
    pending_orders = st.session_state.orders[st.session_state.orders["状态"] == "待备料"]
    st.dataframe(pending_orders[["订单号", "产品", "订单数量"]])
    
    # 模拟缺料计算和状态修改
    order_to_update = st.selectbox("选择订单更新状态", pending_orders["订单号"].tolist() if not pending_orders.empty else ["无待办"])
    if order_to_update != "无待办":
        if st.button("标记为『齐套可生产』"):
            st.session_state.orders.loc[st.session_state.orders["订单号"] == order_to_update, "状态"] = "生产中"
            st.success("状态已更新！")
            st.rerun()

# --- 模块 4: 生产报工 ---
elif menu == "4. 生产报工 (车间)":
    st.header("⚙️ 简单生产报工与 ETA") #
    producing_orders = st.session_state.orders[st.session_state.orders["状态"] == "生产中"]
    
    if producing_orders.empty:
        st.warning("目前没有生产中的订单。")
    else:
        selected_order = st.selectbox("选择报工订单", producing_orders["订单号"])
        order_info = producing_orders[producing_orders["订单号"] == selected_order].iloc[0]
        
        st.write(f"**产品**: {order_info['产品']} | **总数量**: {order_info['订单数量']} | **已完成**: {order_info['已完成数']}")
        
        # 简单报工
        add_qty = st.number_input("今日新增完成数量", min_value=0, step=10)
        daily_capacity = st.number_input("设置该产品日产能 (用于算 ETA)", value=200) #
        
        if st.button("提交报工"):
            new_completed = order_info['已完成数'] + add_qty
            st.session_state.orders.loc[st.session_state.orders["订单号"] == selected_order, "已完成数"] = new_completed
            
            # ETA 计算逻辑
            remaining = order_info['订单数量'] - new_completed
            if remaining <= 0:
                st.session_state.orders.loc[st.session_state.orders["订单号"] == selected_order, "状态"] = "待出货"
                st.success("订单已全部完工，流转至待出货！")
            else:
                eta_days = (remaining // daily_capacity) + (1 if remaining % daily_capacity > 0 else 0)
                st.success(f"报工成功！剩余 {remaining} 件。按照日产能 {daily_capacity}，预计还需要 {eta_days} 天。") #

# --- 模块 5: 出货登记 ---
elif menu == "5. 出货登记 (物流)":
    st.header("🚚 出货登记") #
    shipping_orders = st.session_state.orders[st.session_state.orders["状态"] == "待出货"]
    
    if shipping_orders.empty:
        st.warning("目前没有待出货的订单。")
    else:
        ship_order = st.selectbox("选择发货订单", shipping_orders["订单号"])
        tracking_num = st.text_input("输入物流运单号") #
        
        if st.button("确认发货"):
            if tracking_num:
                st.session_state.orders.loc[st.session_state.orders["订单号"] == ship_order, "运单号"] = tracking_num
                st.session_state.orders.loc[st.session_state.orders["订单号"] == ship_order, "状态"] = "已出货"
                st.success(f"发货成功！运单号：{tracking_num}")
            else:
                st.error("请输入运单号！")
