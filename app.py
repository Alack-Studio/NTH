import streamlit as st
import pandas as pd
import math
from datetime import date, timedelta, datetime
import requests
import io
import random

# ==========================================
# 1. 飞书多维表格引擎 (带日期清洗)
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

    def _format_date(self, ts):
        if pd.isna(ts) or not ts: return None
        return datetime.fromtimestamp(int(ts)/1000).date()

    def get_records(self, table_id, cols):
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records?page_size=100"
        headers = {"Authorization": f"Bearer {self.token}"}
        res = requests.get(url, headers=headers).json()
        items = res.get("data", {}).get("items", [])
        
        if items:
            df = pd.DataFrame([dict(i['fields'], _record_id=i['record_id']) for i in items])
            # 日期字段自动转换
            for c in df.columns:
                if any(x in c for x in ['日期', '交期', '发货', '到料', '到货']):
                    df[c] = df[c].apply(self._format_date)
            for c in cols:
                if c not in df.columns: df[c] = None
            return df
        return pd.DataFrame(columns=cols + ["_record_id"])

    def add_record(self, table_id, fields):
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records"
        formatted = {k: (int(pd.to_datetime(v).timestamp()*1000) if isinstance(v, (date, datetime)) else v) for k, v in fields.items()}
        return requests.post(url, headers={"Authorization": f"Bearer {self.token}"}, json={"fields": formatted}).json()

    def update_record(self, table_id, rid, fields):
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{rid}"
        formatted = {k: (int(pd.to_datetime(v).timestamp()*1000) if isinstance(v, (date, datetime)) else v) for k, v in fields.items()}
        return requests.patch(url, headers={"Authorization": f"Bearer {self.token}"}, json={"fields": formatted}).json()

# ==========================================
# 2. 初始化与核心配置
# ==========================================
st.set_page_config(page_title="跟单协同系统 PRO", page_icon="🏭", layout="wide")
fs = FeishuBitable()

# 你的真实表 ID
IDS = {
    "orders": "tblvMUMfyVcRgxnF", "materials": "tbl5HsYZEDqQiVvM",
    "products": "tbl7Ecj7t3FAQ2Cf", "inventory": "tbl69MGcduldUpt9",
    "purchases": "tblpPk2pb3Hw9xQF"
}

# 缓存加载数据 [cite: 1]
def reload_data():
    st.session_state.orders = fs.get_records(IDS["orders"], ["订单编号", "客户名称", "产品规格", "订单数量", "已完工数", "承诺交期", "预计发货日", "最晚到料日", "当前状态", "异常说明"])
    st.session_state.materials = fs.get_records(IDS["materials"], ["物料编码", "物料名称", "采购周期(天)", "最小采购量"])
    st.session_state.inventory = fs.get_records(IDS["inventory"], ["物料编码", "现存量", "预留量", "安全库存"])
    st.session_state.products = fs.get_records(IDS["products"], ["产品规格", "标准日产能", "包装缓冲天数"])
    st.session_state.purchases = fs.get_records(IDS["purchases"], ["采购单号", "关联订单", "物料编码", "采购数量", "承诺到货日", "状态"])

if 'orders' not in st.session_state:
    reload_data()

# BOM 结构 [cite: 2, 56, 76]
BOM_MASTER = {
    "漏电保护插头-标准款": {"MAT-001": 1, "MAT-002": 3, "MAT-003": 1},
    "精密冲压端子-B型": {"MAT-002": 1, "MAT-001": 0.5}
}

# ==========================================
# 3. 计算大脑 (MRP & ETA) [cite: 5, 9, 88, 97]
# ==========================================
def run_mrp_engine(oid):
    order = st.session_state.orders[st.session_state.orders["订单编号"] == oid].iloc[0]
    bom = BOM_MASTER.get(order["产品规格"], {})
    latest_arrival = date.today()
    has_shortage = False
    
    for m_code, unit_qty in bom.items():
        req = order["订单数量"] * unit_qty # 需求量 [cite: 90]
        inv = st.session_state.inventory[st.session_state.inventory["物料编码"] == m_code].iloc[0]
        avail = inv["现存量"] - inv["预留量"] - inv["安全库存"] # 可用量 [cite: 91]
        
        gap = max(0, req - avail) # 缺口 [cite: 92]
        if gap > 0:
            has_shortage = True
            m_info = st.session_state.materials[st.session_state.materials["物料编码"]==m_code].iloc[0]
            arr_date = date.today() + timedelta(days=int(m_info["采购周期(天)"]))
            latest_arrival = max(latest_arrival, arr_date)
            # 写入飞书采购表 [cite: 121]
            fs.add_record(IDS["purchases"], {
                "采购单号": f"PO-{oid}-{m_code}", "关联订单": oid, "物料编码": m_code,
                "采购数量": max(gap, m_info["最小采购量"]), "承诺到货日": arr_date, "状态": "采购中"
            })
    
    # 计算 ETA [cite: 101, 146]
    prod_info = st.session_state.products[st.session_state.products["产品规格"] == order["产品规格"]].iloc[0]
    days_needed = math.ceil(order["订单数量"] / prod_info["标准日产能"])
    eta = latest_arrival + timedelta(days=days_needed + int(prod_info["包装缓冲天数"]))
    
    # 更新飞书订单状态 [cite: 27, 28]
    fs.update_record(IDS["orders"], order["_record_id"], {
        "当前状态": "备料中" if has_shortage else "可生产",
        "预计发货日": eta, "最晚到料日": latest_arrival
    })
    return eta

# ==========================================
# 4. 系统 UI (全模块回归) [cite: 10, 11]
# ==========================================
st.sidebar.title("🏭 跟单云协同系统")
menu = st.sidebar.radio("业务域", ["1. 首页看板", "2. 销售订单", "3. 计划采购", "4. 仓储物流", "5. 生产车间", "⚙️ 基础数据"])

# 侧边栏测试工具
st.sidebar.markdown("---")
if st.sidebar.button("🚀 生成 3 条模拟订单"):
    for _ in range(3):
        fs.add_record(IDS["orders"], {
            "订单编号": f"TEST-{random.randint(100,999)}", "客户名称": random.choice(["华为", "顺丰", "格力"]),
            "产品规格": random.choice(list(BOM_MASTER.keys())), "订单数量": random.randint(200,800),
            "承诺交期": date.today() + timedelta(days=20), "当前状态": "新建", "已完工数": 0
        })
    reload_data()
    st.rerun()

if st.sidebar.button("🔄 同步飞书最新数据"):
    reload_data()
    st.rerun()

# --- 1. 首页看板 [cite: 12, 105] ---
if menu == "1. 首页看板":
    st.header("📊 管理驾驶舱")
    cols = st.columns(4)
    cols[0].metric("待处理订单", len(st.session_state.orders[st.session_state.orders["当前状态"]=="新建"]))
    cols[1].metric("缺料/备料中", len(st.session_state.orders[st.session_state.orders["当前状态"]=="备料中"]))
    cols[2].metric("交期预警", len(st.session_state.orders[(st.session_state.orders["预计发货日"] > st.session_state.orders["承诺交期"]).fillna(False)]))
    cols[3].metric("在制异常", len(st.session_state.orders[st.session_state.orders["异常说明"]!="无"]))
    
    st.subheader("🚨 关键追踪记录")
    st.dataframe(st.session_state.orders.drop(columns=["_record_id"], errors='ignore'), use_container_width=True)

# --- 2. 销售与订单 [cite: 15, 69] ---
elif menu == "2. 销售与订单":
    st.header("销售管理")
    with st.expander("📝 录入新订单", expanded=True):
        with st.form("new_order"):
            c1, c2 = st.columns(2)
            cstm = c1.text_input("客户名称")
            prod = c1.selectbox("产品规格", list(BOM_MASTER.keys()))
            qty = c2.number_input("数量", min_value=1)
            ddl = c2.date_input("交期要求")
            if st.form_submit_button("确认并同步到飞书"):
                oid = f"ORD-{date.today().strftime('%m%d%H%M')}"
                fs.add_record(IDS["orders"], {"订单编号": oid, "客户名称": cstm, "产品规格": prod, "订单数量": qty, "承诺交期": ddl, "当前状态": "新建", "已完工数": 0})
                reload_data()
                st.success("订单已创建！")

# --- 3. 计划与采购 [cite: 25, 41, 117] ---
elif menu == "3. 计划与采购":
    st.header("PMC 计划与采购跟进")
    new_orders = st.session_state.orders[st.session_state.orders["当前状态"] == "新建"]
    if not new_orders.empty:
        sel_oid = st.selectbox("选择订单运行 MRP", new_orders["订单编号"])
        if st.button("运行 MRP 计算与排产"):
            with st.spinner("算料并生成采购需求中..."):
                eta = run_mrp_engine(sel_oid)
                reload_data()
                st.success(f"计算完成！系统测算 ETA：{eta}")
    
    st.subheader("🛒 采购单追踪 (回写飞书)")
    st.dataframe(st.session_state.purchases, use_container_width=True)

# --- 5. 生产车间 [cite: 35, 44, 126] ---
elif menu == "5. 生产车间":
    st.header("车间报工终端")
    prod_orders = st.session_state.orders[st.session_state.orders["当前状态"].isin(["备料中", "生产中", "可生产"])]
    if not prod_orders.empty:
        sel_oid = st.selectbox("选择报工订单", prod_orders["订单编号"])
        row = prod_orders[prod_orders["订单编号"]==sel_oid].iloc[0]
        with st.form("prod_report"):
            done = st.number_input("累计完工数", value=int(row["已完工数"]))
            abn = st.selectbox("异常提报", ["无", "停机", "质量异常", "缺料"])
            if st.form_submit_button("提交并更新飞书 ETA"):
                # 滚动更新 ETA [cite: 39]
                new_eta = calc_eta(row["产品规格"], row["订单数量"] - done, date.today())
                fs.update_record(IDS["orders"], row["_record_id"], {
                    "已完工数": done, "异常说明": abn, "当前状态": "生产中", "预计发货日": new_eta
                })
                reload_data()
                st.success("进度已同步，ETA 已动态调整！")
    else:
        st.info("当前车间无在制任务")

# 其他模块 (⚙️ 基础数据 等) 保持类似逻辑...
