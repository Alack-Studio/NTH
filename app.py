import streamlit as st
import pandas as pd
import math
from datetime import date, timedelta, datetime
import requests
import io
import random

# ==========================================
# 1. 飞书多维表格云端连接器 (全功能同步版)
# ==========================================
class FeishuBitable:
    def __init__(self):
        self.app_id = st.secrets["feishu"]["app_id"]
        self.app_secret = st.secrets["feishu"]["app_secret"]
        self.app_token = st.secrets["feishu"]["app_token"]
        self.token = self._get_token()

    def _get_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        res = requests.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret})
        return res.json().get("tenant_access_token")

    def _format_date_from_fs(self, ts):
        """将飞书毫秒时间戳转换为 Python date 对象"""
        if pd.isna(ts) or ts == "" or ts is None: return None
        try:
            return datetime.fromtimestamp(int(ts)/1000).date()
        except:
            return None

    def get_records(self, table_id, default_columns):
        if not table_id.startswith("tbl"):
            return pd.DataFrame(columns=default_columns + ["_record_id"])
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records?page_size=100"
        headers = {"Authorization": f"Bearer {self.token}"}
        res = requests.get(url, headers=headers)
        items = res.json().get("data", {}).get("items", [])
        
        if items:
            data_list = []
            for i in items:
                row = i['fields']
                row['_record_id'] = i['record_id']
                # 自动处理日期字段转换
                for k, v in row.items():
                    if '日期' in k or '交期' in k or '发货' in k or '到料' in k or '到货' in k:
                        row[k] = self._format_date_from_fs(v)
                data_list.append(row)
            df = pd.DataFrame(data_list)
            for col in default_columns:
                if col not in df.columns: df[col] = None
            return df
        return pd.DataFrame(columns=default_columns + ["_record_id"])

    def add_record(self, table_id, fields):
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records"
        headers = {"Authorization": f"Bearer {self.token}"}
        formatted_fields = {}
        for k, v in fields.items():
            if isinstance(v, (date, pd.Timestamp)):
                formatted_fields[k] = int(pd.to_datetime(v).timestamp() * 1000)
            else:
                formatted_fields[k] = v
        return requests.post(url, headers=headers, json={"fields": formatted_fields}).json()

    def update_record(self, table_id, record_id, fields):
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{record_id}"
        headers = {"Authorization": f"Bearer {self.token}"}
        formatted_fields = {}
        for k, v in fields.items():
            if isinstance(v, (date, pd.Timestamp)):
                formatted_fields[k] = int(pd.to_datetime(v).timestamp() * 1000)
            else:
                formatted_fields[k] = v
        return requests.patch(url, headers=headers, json={"fields": formatted_fields}).json()

# ==========================================
# 2. 初始化与数据加载
# ==========================================
st.set_page_config(page_title="手搓跟单系统 V2", page_icon="🏭", layout="wide")
bitable = FeishuBitable()

IDS = {
    "orders": "tblvMUMfyVcRgxnF", "materials": "tbl5HsYZEDqQiVvM",
    "products": "tbl7Ecj7t3FAQ2Cf", "inventory": "tbl69MGcduldUpt9",
    "purchases": "tblpPk2pb3Hw9xQF"
}

def reload_all_data():
    st.session_state.orders = bitable.get_records(IDS["orders"], ["订单编号", "客户名称", "产品规格", "订单数量", "已完工数", "承诺交期", "预计发货日", "最晚到料日", "当前状态", "异常说明"])
    st.session_state.materials = bitable.get_records(IDS["materials"], ["物料编码", "物料名称", "采购周期(天)", "最小采购量"])
    st.session_state.inventory = bitable.get_records(IDS["inventory"], ["物料编码", "现存量", "预留量", "安全库存"])
    st.session_state.products = bitable.get_records(IDS["products"], ["产品规格", "标准日产能", "包装缓冲天数"])
    st.session_state.purchases = bitable.get_records(IDS["purchases"], ["采购单号", "关联订单", "物料编码", "采购数量", "承诺到货日", "状态"])

if 'orders' not in st.session_state:
    with st.spinner("正在从飞书云端同步数据..."):
        reload_all_data()

BOM_MASTER = {
    "漏电保护插头-标准款": {"MAT-001": 1, "MAT-002": 3, "MAT-003": 1},
    "精密冲压端子-B型": {"MAT-002": 1, "MAT-001": 0.5}
}

# ==========================================
# 3. 业务逻辑函数
# ==========================================
def calc_eta(product_name, remaining_qty, start_date):
    if remaining_qty <= 0: return date.today()
    try:
        prod_info = st.session_state.products[st.session_state.products["产品规格"] == product_name].iloc[0]
        days = math.ceil(remaining_qty / prod_info["标准日产能"])
        return start_date + timedelta(days=days + int(prod_info["包装缓冲天数"]))
    except: return start_date + timedelta(days=7)

# ==========================================
# 4. 侧边栏与菜单
# ==========================================
st.sidebar.title("🏭 跟单协同系统")
menu = st.sidebar.radio("业务功能模块", ["1. 首页看板", "2. 销售与订单", "3. 计划与采购", "4. 仓储物流", "5. 生产车间", "⚙️ 基础数据"])

st.sidebar.markdown("---")
if st.sidebar.button("🔄 刷新全表数据"):
    reload_all_data()
    st.rerun()

if st.sidebar.button("🚀 生成3条测试订单"):
    for _ in range(3):
        new_order = {
            "订单编号": f"TEST-{random.randint(100,999)}", "客户名称": random.choice(["客户A", "客户B"]),
            "产品规格": random.choice(list(BOM_MASTER.keys())), "订单数量": random.randint(100,500),
            "已完工数": 0, "承诺交期": date.today() + timedelta(days=15), "当前状态": "新建"
        }
        bitable.add_record(IDS["orders"], new_order)
    reload_all_data()
    st.rerun()

# ==========================================
# 5. 各页面实现
# ==========================================

# --- 1. 首页看板 ---
if menu == "1. 首页看板":
    st.header("📊 管理驾驶舱")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("待处理订单", len(st.session_state.orders[st.session_state.orders["当前状态"]=="新建"]))
    c2.metric("在制工单", len(st.session_state.orders[st.session_state.orders["当前状态"]=="生产中"]))
    c3.metric("待入库采购", len(st.session_state.purchases[st.session_state.purchases["状态"]=="采购中"]))
    c4.metric("交期预警", len(st.session_state.orders[(st.session_state.orders["预计发货日"].notna()) & (st.session_state.orders["预计发货日"] > st.session_state.orders["承诺交期"])]))
    
    st.subheader("📋 订单实时追踪")
    st.dataframe(st.session_state.orders.drop(columns=["_record_id"], errors='ignore'), use_container_width=True)

# --- 2. 销售与订单 ---
elif menu == "2. 销售与订单":
    st.header("订单管理中心")
    tab1, tab2 = st.tabs(["📝 新增订单", "🔍 订单台账"])
    with tab1:
        with st.form("add_o"):
            c1, c2 = st.columns(2)
            cstm = c1.text_input("客户名称")
            prod = c1.selectbox("产品规格", list(BOM_MASTER.keys()))
            qty = c2.number_input("订单数量", min_value=1)
            ddl = c2.date_input("承诺交期")
            if st.form_submit_button("同步至飞书并下单"):
                oid = f"ORD-{date.today().strftime('%m%d%H%M')}"
                fields = {"订单编号": oid, "客户名称": cstm, "产品规格": prod, "订单数量": qty, "承诺交期": ddl, "当前状态": "新建", "已完工数": 0}
                bitable.add_record(IDS["orders"], fields)
                reload_all_data()
                st.success("下单成功！")
    with tab2:
        st.dataframe(st.session_state.orders)

# --- 3. 计划与采购 ---
elif menu == "3. 计划与采购":
    st.header("PMC 计划协同")
    new_orders = st.session_state.orders[st.session_state.orders["当前状态"] == "新建"]
    if not new_orders.empty:
        sel_oid = st.selectbox("选择待排产订单", new_orders["订单编号"])
        if st.button("运行 MRP 并生成采购单"):
            order = new_orders[new_orders["订单编号"] == sel_oid].iloc[0]
            # 简易MRP逻辑并回写飞书
            bom = BOM_MASTER.get(order["产品规格"], {})
            latest_arr = date.today()
            for m_code, u_qty in bom.items():
                m_info = st.session_state.materials[st.session_state.materials["物料编码"]==m_code].iloc[0]
                arr_date = date.today() + timedelta(days=int(m_info["采购周期(天)"]))
                latest_arr = max(latest_arr, arr_date)
                # 写入采购单到飞书
                bitable.add_record(IDS["purchases"], {
                    "采购单号": f"PO-{sel_oid}-{m_code}", "关联订单": sel_oid,
                    "物料编码": m_code, "采购数量": order["订单数量"]*u_qty,
                    "承诺到货日": arr_date, "状态": "采购中"
                })
            # 更新订单状态和ETA到飞书
            eta = calc_eta(order["产品规格"], order["订单数量"], latest_arr + timedelta(days=1))
            bitable.update_record(IDS["orders"], order["_record_id"], {
                "当前状态": "备料中", "预计发货日": eta, "最晚到料日": latest_arr
            })
            reload_all_data()
            st.success("MRP运行完成，采购单已同步至飞书！")
    else:
        st.info("没有待排产的新订单")
    st.subheader("采购在途追踪")
    st.dataframe(st.session_state.purchases)

# --- 4. 仓储物流 ---
elif menu == "4. 仓储物流":
    st.header("仓库作业中心")
    tab1, tab2 = st.tabs(["📦 采购入库", "🚚 库存概览"])
    with tab1:
        active_po = st.session_state.purchases[st.session_state.purchases["状态"]=="采购中"]
        if not active_po.empty:
            sel_po = st.selectbox("选择入库单", active_po["采购单号"])
            if st.button("确认收货入库"):
                po_row = active_po[active_po["采购单号"]==sel_po].iloc[0]
                bitable.update_record(IDS["purchases"], po_row["_record_id"], {"状态": "已入库"})
                # 这里可以增加更新库存表的逻辑
                reload_all_data()
                st.success("入库成功！")
    with tab2:
        st.dataframe(st.session_state.inventory)

# --- 5. 生产车间 ---
elif menu == "5. 生产车间":
    st.header("车间报工终端")
    prod_orders = st.session_state.orders[st.session_state.orders["当前状态"].isin(["备料中", "生产中", "可生产"])]
    if not prod_orders.empty:
        sel_oid = st.selectbox("选择报工订单", prod_orders["订单编号"])
        row = prod_orders[prod_orders["订单编号"] == sel_oid].iloc[0]
        with st.form("rp"):
            done = st.number_input("累计完工数量", value=int(row["已完工数"] or 0))
            status = st.selectbox("更新状态", ["生产中", "待出货"])
            if st.form_submit_button("提交报工数据"):
                # 重新算ETA
                new_eta = calc_eta(row["产品规格"], row["订单数量"] - done, date.today())
                bitable.update_record(IDS["orders"], row["_record_id"], {
                    "已完工数": done, "当前状态": status, "预计发货日": new_eta
                })
                reload_all_data()
                st.success("报工成功，飞书已同步！")
    else:
        st.info("暂无在制任务")

# --- 6. 基础数据 ---
elif menu == "⚙️ 基础数据":
    st.header("基础档案管理")
    st.subheader("物料档案 (从飞书读取)")
    st.dataframe(st.session_state.materials, use_container_width=True)
    st.subheader("产品产能 (从飞书读取)")
    st.dataframe(st.session_state.products, use_container_width=True)
    
    st.sidebar.download_button("📥 下载飞书初始化模板", data="请使用之前生成的Excel", file_name="template.xlsx")
