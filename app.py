import streamlit as st
import pandas as pd
import math
from datetime import date, timedelta, datetime
import requests
import random

# ==========================================
# 1. 飞书 Bitable 核心同步引擎
# ==========================================
class FeishuConnector:
    def __init__(self):
        try:
            self.app_id = st.secrets["feishu"]["app_id"]
            self.app_secret = st.secrets["feishu"]["app_secret"]
            self.app_token = st.secrets["feishu"]["app_token"]
            self.token = self._get_tenant_token()
        except Exception as e:
            st.error(f"❌ 密钥缺失！请在 Streamlit Secrets 中配置 feishu 字段。")
            st.stop()

    def _get_tenant_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        res = requests.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret}).json()
        if res.get("code") != 0:
            st.error(f"❌ 飞书授权失败：{res.get('msg')} (请确认 App Secret 是否为 S5HebPkziaRw80sdjSrcZczXnRf)")
            return None
        return res.get("tenant_access_token")

    def get_df(self, table_id, columns):
        """全自动拉取并清洗数据"""
        if not self.token: return pd.DataFrame(columns=columns)
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records?page_size=100"
        headers = {"Authorization": f"Bearer {self.token}"}
        data = requests.get(url, headers=headers).json()
        
        items = data.get("data", {}).get("items", [])
        if items:
            df = pd.DataFrame([dict(i['fields'], _rid=i['record_id']) for i in items])
            # 日期字段毫秒转日期对象 [cite: 4, 16]
            for col in df.columns:
                if any(x in col for x in ['日期', '交期', '发货', '到货', '到料']):
                    df[col] = pd.to_datetime(df[col], unit='ms').dt.date
            for c in columns:
                if c not in df.columns: df[c] = None
            return df
        return pd.DataFrame(columns=columns + ["_rid"])

    def add(self, table_id, fields):
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records"
        payload = {k: (int(pd.to_datetime(v).timestamp() * 1000) if isinstance(v, (date, datetime)) else v) for k, v in fields.items()}
        return requests.post(url, headers={"Authorization": f"Bearer {self.token}"}, json={"fields": payload}).json()

    def update(self, table_id, rid, fields):
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{rid}"
        payload = {k: (int(pd.to_datetime(v).timestamp() * 1000) if isinstance(v, (date, datetime)) else v) for k, v in fields.items()}
        return requests.patch(url, headers={"Authorization": f"Bearer {self.token}"}, json={"fields": payload}).json()

# ==========================================
# 2. 角色逻辑与自动同步 [cite: 40-49]
# ==========================================
st.set_page_config(page_title="跟单协同系统 PRO", page_icon="🏭", layout="wide")
feishu = FeishuConnector()

IDS = {
    "orders": "tblvMUMfyVcRgxnF", "materials": "tbl5HsYZEDqQiVvM",
    "products": "tbl7Ecj7t3FAQ2Cf", "inventory": "tbl69MGcduldUpt9",
    "purchases": "tblpPk2pb3Hw9xQF"
}

# --- 自动同步：每次刷新页面都会运行 ---
def auto_sync_data():
    st.session_state.orders = feishu.get_df(IDS["orders"], ["订单编号", "客户名称", "产品规格", "订单数量", "已完工数", "承诺交期", "预计发货日", "最晚到料日", "当前状态", "异常说明", "收款情况"])
    st.session_state.materials = feishu.get_df(IDS["materials"], ["物料编码", "物料名称", "采购周期(天)", "最小采购量"])
    st.session_state.inventory = feishu.get_df(IDS["inventory"], ["物料编码", "现存量", "预留量", "安全库存"])
    st.session_state.products = feishu.get_df(IDS["products"], ["产品规格", "标准日产能", "包装缓冲天数"])
    st.session_state.purchases = feishu.get_df(IDS["purchases"], ["采购单号", "关联订单", "物料编码", "采购数量", "承诺到货日", "状态"])

auto_sync_data()

# BOM 模板 [cite: 56, 76]
BOM_MASTER = {
    "漏电保护插头-标准款": {"MAT-001": 1, "MAT-002": 3, "MAT-003": 1},
    "精密冲压端子-B型": {"MAT-002": 1, "MAT-001": 0.5}
}

# ==========================================
# 3. 核心算法 (MRP & ETA) [cite: 88-104]
# ==========================================
def run_mrp_calculation(oid):
    """根据库存可用量计算缺口并排产 [cite: 91-96]"""
    order = st.session_state.orders[st.session_state.orders["订单编号"] == oid].iloc[0]
    bom = BOM_MASTER.get(order["产品规格"], {})
    latest_arrival = date.today()
    shortage_flag = False
    
    for m_code, u_qty in bom.items():
        need = order["订单数量"] * u_qty
        # 可用量 = 现存 - 预留 - 安全 [cite: 57, 91]
        try:
            inv = st.session_state.inventory[st.session_state.inventory["物料编码"] == m_code].iloc[0]
            avail = (inv["现存量"] or 0) - (inv["预留量"] or 0) - (inv["安全库存"] or 0)
        except: avail = 0
        
        gap = max(0, need - avail)
        if gap > 0:
            shortage_flag = True
            m_info = st.session_state.materials[st.session_state.materials["物料编码"]==m_code].iloc[0]
            arrival = date.today() + timedelta(days=int(m_info["采购周期(天)"] or 7))
            latest_arrival = max(latest_arrival, arrival)
            # 生成飞书采购需求 [cite: 58, 82]
            feishu.add(IDS["purchases"], {
                "采购单号": f"PO-{oid}-{m_code}", "关联订单": oid, "物料编码": m_code,
                "采购数量": max(gap, m_info["最小采购量"] or 0), "承诺到货日": arrival, "状态": "采购中"
            })

    # ETA 滚动预测：最晚到料日 + 生产天数 + 缓冲 [cite: 101-104]
    try:
        prod_data = st.session_state.products[st.session_state.products["产品规格"] == order["产品规格"]].iloc[0]
        p_days = math.ceil(order["订单数量"] / (prod_data["标准日产能"] or 100))
        eta = latest_arrival + timedelta(days=p_days + int(prod_data["包装缓冲天数"] or 1))
    except: eta = latest_arrival + timedelta(days=7)
    
    # 回写飞书订单表
    feishu.update(IDS["orders"], order["_rid"], {
        "当前状态": "备料中" if shortage_flag else "可生产",
        "预计发货日": eta, "最晚到料日": latest_arrival
    })
    return eta

# ==========================================
# 4. 业务界面实现 [cite: 105-130]
# ==========================================
st.sidebar.title("🏭 跟单协同云系统")
menu = st.sidebar.radio("核心业务域", ["1. 首页看板", "2. 销售订单", "3. 计划采购", "4. 仓储物流", "5. 生产车间", "⚙️ 基础数据"])

st.sidebar.markdown("---")
if st.sidebar.button("🚀 一键生成 3 条测试订单"):
    with st.spinner("同步数据中..."):
        for _ in range(3):
            feishu.add(IDS["orders"], {
                "订单编号": f"TEST-{random.randint(100,999)}", "客户名称": random.choice(["华东科技", "比亚迪", "华为"]),
                "产品规格": random.choice(list(BOM_MASTER.keys())), "订单数量": random.randint(200,800),
                "承诺交期": date.today() + timedelta(days=15), "当前状态": "新建", "已完工数": 0, "收款情况": "未收款"
            })
        st.rerun()

# --- 1. 首页看板 [cite: 105-107] ---
if menu == "1. 首页看板":
    st.header("📊 管理驾驶舱 (总览)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("待备料订单", len(st.session_state.orders[st.session_state.orders["当前状态"]=="新建"]))
    c2.metric("缺料备料中", len(st.session_state.orders[st.session_state.orders["当前状态"]=="备料中"]))
    c3.metric("在制异常", len(st.session_state.orders[st.session_state.orders["异常说明"]!="无"]))
    # 交期风险逻辑 [cite: 139]
    risk_count = len(st.session_state.orders[(st.session_state.orders["预计发货日"] > st.session_state.orders["承诺交期"]).fillna(False)])
    c4.metric("交期风险", risk_count)
    
    st.subheader("📋 实时跟单台账 (飞书数据源)")
    st.dataframe(st.session_state.orders.drop(columns=["_rid"], errors="ignore"), use_container_width=True)

# --- 2. 销售订单 [cite: 51-53] ---
elif menu == "2. 销售订单":
    st.header("销售下单中心")
    with st.form("order_form"):
        c1, c2 = st.columns(2)
        cstm = c1.text_input("客户名称")
        plist = st.session_state.products["产品规格"].tolist() if not st.session_state.products.empty else list(BOM_MASTER.keys())
        prod = c1.selectbox("选择产品规格", plist)
        qty = c2.number_input("需求数量", min_value=1)
        ddl = c2.date_input("交期要求")
        if st.form_submit_button("确认下单并同步飞书", type="primary"):
            oid = f"ORD-{datetime.now().strftime('%m%d%H%M')}"
            feishu.add(IDS["orders"], {"订单编号": oid, "客户名称": cstm, "产品规格": prod, "订单数量": qty, "承诺交期": ddl, "当前状态": "新建", "已完工数": 0, "收款情况": "未收款"})
            st.rerun()

# --- 3. 计划采购 [cite: 117-122] ---
elif menu == "3. 计划采购":
    st.header("PMC 计划与采购协同")
    unprocessed = st.session_state.orders[st.session_state.orders["当前状态"] == "新建"]
    if not unprocessed.empty:
        sel_oid = st.selectbox("选择订单运行 MRP", unprocessed["订单编号"])
        if st.button("运行 MRP 算料并自动生成采购单"):
            eta = run_mrp_calculation(sel_oid)
            st.success(f"排产完成！系统已同步采购需求至飞书。预计发货日：{eta}")
            st.rerun()
    else: st.info("目前没有待处理的新订单。")
    st.subheader("🛒 采购跟进 (飞书同步)")
    st.dataframe(st.session_state.purchases, use_container_width=True)

# --- 5. 生产车间 [cite: 126-128] ---
elif menu == "5. 生产车间":
    st.header("车间报工终端")
    active_jobs = st.session_state.orders[st.session_state.orders["当前状态"].isin(["备料中", "生产中", "可生产"])]
    if not active_jobs.empty:
        sel_oid = st.selectbox("选择报工订单", active_jobs["订单编号"])
        row = active_jobs[active_jobs["订单编号"]==sel_oid].iloc[0]
        with st.form("prod_rp"):
            done = st.number_input("累计产出数量", value=int(row["已完工数"] or 0))
            abn = st.selectbox("异常提报", ["无", "停机", "质量异常", "缺料"])
            if st.form_submit_button("确认报工"):
                # 报工自动重算预计发货日 [cite: 100-101]
                p_info = st.session_state.products[st.session_state.products["产品规格"]==row["产品规格"]].iloc[0]
                rem_qty = max(0, row["订单数量"] - done)
                rem_days = math.ceil(rem_qty / (p_info["标准日产能"] or 100))
                new_eta = date.today() + timedelta(days=rem_days + 1)
                feishu.update(IDS["orders"], row["_rid"], {
                    "已完工数": done, "异常说明": abn, "当前状态": "生产中" if done < row["订单数量"] else "待出货",
                    "预计发货日": new_eta
                })
                st.rerun()
    else: st.info("暂无生产任务。")

# --- 6. 基础数据 [cite: 74-80] ---
elif menu == "⚙️ 基础数据":
    st.header("主数据库档案 (飞书同步)")
    st.write("物料清单：")
    st.table(st.session_state.materials)
    st.write("产能基准：")
    st.table(st.session_state.products)
