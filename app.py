import streamlit as st
import pandas as pd
import math
from datetime import date, timedelta, datetime
import requests
import random

# ==========================================
# 1. 飞书 Bitable 核心引擎 (加强报错版)
# ==========================================
class FeishuConnector:
    def __init__(self):
        try:
            # 校验 Secrets 是否配置
            self.app_id = st.secrets["feishu"]["app_id"]
            self.app_secret = st.secrets["feishu"]["app_secret"]
            self.app_token = st.secrets["feishu"]["app_token"]
            self.token = self._get_tenant_token()
        except Exception as e:
            st.error(f"❌ Streamlit Secrets 配置缺失或错误！请检查后台设置。错误: {e}")
            st.stop()

    def _get_tenant_token(self):
        """获取飞书自建应用授权码"""
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        res = requests.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret}).json()
        if res.get("code") != 0:
            st.error(f"❌ 无法连接飞书 API：{res.get('msg')} (请检查 App ID 和 Secret 是否正确)")
            return None
        return res.get("tenant_access_token")

    def get_df(self, table_id, columns):
        """拉取飞书数据并清洗"""
        if not self.token: return pd.DataFrame(columns=columns)
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records?page_size=100"
        headers = {"Authorization": f"Bearer {self.token}"}
        data = requests.get(url, headers=headers).json()
        
        items = data.get("data", {}).get("items", [])
        if items:
            df = pd.DataFrame([dict(i['fields'], _rid=i['record_id']) for i in items])
            # 自动处理飞书日期(毫秒)转 Python 日期
            for col in df.columns:
                if any(x in col for x in ['日期', '交期', '发货', '到货', '到料']):
                    df[col] = pd.to_datetime(df[col], unit='ms').dt.date
            # 确保列名对齐，防止报错
            for c in columns:
                if c not in df.columns: df[c] = None
            return df
        return pd.DataFrame(columns=columns + ["_rid"])

    def add(self, table_id, fields):
        """写入飞书：自动处理日期格式"""
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records"
        # 飞书 API 要求日期为时间戳
        payload = {k: (int(pd.to_datetime(v).timestamp() * 1000) if isinstance(v, (date, datetime)) else v) for k, v in fields.items()}
        return requests.post(url, headers={"Authorization": f"Bearer {self.token}"}, json={"fields": payload}).json()

    def update(self, table_id, rid, fields):
        """更新飞书指定行"""
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{rid}"
        payload = {k: (int(pd.to_datetime(v).timestamp() * 1000) if isinstance(v, (date, datetime)) else v) for k, v in fields.items()}
        return requests.patch(url, headers={"Authorization": f"Bearer {self.token}"}, json={"fields": payload}).json()

# ==========================================
# 2. 初始化与自动加载
# ==========================================
st.set_page_config(page_title="跟单云协同系统", page_icon="🏭", layout="wide")
feishu = FeishuConnector()

# 真实表格 ID 
IDS = {
    "orders": "tblvMUMfyVcRgxnF", "materials": "tbl5HsYZEDqQiVvM",
    "products": "tbl7Ecj7t3FAQ2Cf", "inventory": "tbl69MGcduldUpt9",
    "purchases": "tblpPk2pb3Hw9xQF"
}

# 自动刷新数据：每次脚本运行都会执行
def load_all_data():
    st.session_state.orders = feishu.get_df(IDS["orders"], ["订单编号", "客户名称", "产品规格", "订单数量", "已完工数", "承诺交期", "预计发货日", "最晚到料日", "当前状态", "异常说明"])
    st.session_state.materials = feishu.get_df(IDS["materials"], ["物料编码", "物料名称", "采购周期(天)", "最小采购量"])
    st.session_state.inventory = feishu.get_df(IDS["inventory"], ["物料编码", "现存量", "预留量", "安全库存"])
    st.session_state.products = feishu.get_df(IDS["products"], ["产品规格", "标准日产能", "包装缓冲天数"])
    st.session_state.purchases = feishu.get_df(IDS["purchases"], ["采购单号", "关联订单", "物料编码", "采购数量", "承诺到货日", "状态"])

load_all_data()

# BOM 模板 [cite: 56]
BOM_MASTER = {
    "漏电保护插头-标准款": {"MAT-001": 1, "MAT-002": 3, "MAT-003": 1},
    "精密冲压端子-B型": {"MAT-002": 1, "MAT-001": 0.5}
}

# ==========================================
# 3. 计算引擎 (MRP & ETA)
# ==========================================
def run_mrp_logic(oid):
    order = st.session_state.orders[st.session_state.orders["订单编号"] == oid].iloc[0]
    bom = BOM_MASTER.get(order["产品规格"], {})
    latest_arrival = date.today()
    has_gap = False
    
    for m_code, unit_qty in bom.items():
        need = order["订单数量"] * unit_qty
        # 公式：可用量 = 现存 - 预留 - 安全 
        try:
            inv = st.session_state.inventory[st.session_state.inventory["物料编码"] == m_code].iloc[0]
            avail = (inv["现存量"] or 0) - (inv["预留量"] or 0) - (inv["安全库存"] or 0)
        except: avail = 0
        
        gap = max(0, need - avail) # [cite: 92]
        if gap > 0:
            has_gap = True
            m_info = st.session_state.materials[st.session_state.materials["物料编码"]==m_code].iloc[0]
            arr_date = date.today() + timedelta(days=int(m_info["采购周期(天)"] or 7)) # [cite: 95]
            latest_arrival = max(latest_arrival, arr_date)
            # 自动生成采购单 [cite: 93]
            feishu.add(IDS["purchases"], {
                "采购单号": f"PO-{oid}-{m_code}", "关联订单": oid, "物料编码": m_code,
                "采购数量": max(gap, m_info["最小采购量"] or 0), "承诺到货日": arr_date, "状态": "采购中"
            })

    # ETA 公式：最晚到料日 + 生产天数 + 缓冲 
    try:
        prod = st.session_state.products[st.session_state.products["产品规格"] == order["产品规格"]].iloc[0]
        days = math.ceil(order["订单数量"] / (prod["标准日产能"] or 100))
        eta = latest_arrival + timedelta(days=days + int(prod["包装缓冲天数"] or 1))
    except: eta = latest_arrival + timedelta(days=7)
    
    # 更新订单状态回飞书
    feishu.update(IDS["orders"], order["_rid"], {
        "当前状态": "备料中" if has_gap else "可生产",
        "预计发货日": eta, "最晚到料日": latest_arrival
    })
    return eta

# ==========================================
# 4. 业务界面实现
# ==========================================
st.sidebar.title("🏭 跟单云协同系统")
menu = st.sidebar.radio("核心业务模块", ["1. 首页看板", "2. 销售下单", "3. 计划与采购", "4. 仓储物流", "5. 车间报工", "⚙️ 基础数据"])

st.sidebar.markdown("---")
# 功能：一键测试
if st.sidebar.button("🚀 生成 3 条随机测试订单"):
    with st.spinner("同步至飞书..."):
        for _ in range(3):
            feishu.add(IDS["orders"], {
                "订单编号": f"TEST-{random.randint(100,999)}", "客户名称": random.choice(["华为", "比亚迪", "顺丰"]),
                "产品规格": random.choice(list(BOM_MASTER.keys())), "订单数量": random.randint(200,1000),
                "承诺交期": date.today() + timedelta(days=15), "当前状态": "新建", "已完工数": 0
            })
        st.rerun()

# --- 1. 首页看板 [cite: 105] ---
if menu == "1. 首页看板":
    st.header("📊 管理驾驶舱 (总览)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("待备料订单", len(st.session_state.orders[st.session_state.orders["当前状态"]=="新建"]))
    c2.metric("缺料/备料中", len(st.session_state.orders[st.session_state.orders["当前状态"]=="备料中"]))
    c3.metric("在制异常", len(st.session_state.orders[st.session_state.orders["异常说明"]!="无"]))
    c4.metric("交期风险", len(st.session_state.orders[(st.session_state.orders["预计发货日"] > st.session_state.orders["承诺交期"]).fillna(False)]))
    
    st.subheader("📋 实时订单追踪台账")
    st.dataframe(st.session_state.orders.drop(columns=["_rid"], errors='ignore'), use_container_width=True)

# --- 2. 销售下单 [cite: 51] ---
elif menu == "2. 销售下单":
    st.header("新订单录入")
    with st.form("new_order"):
        c1, c2 = st.columns(2)
        cstm = c1.text_input("客户名称")
        # 自动获取产品表里的规格
        plist = st.session_state.products["产品规格"].tolist() if not st.session_state.products.empty else list(BOM_MASTER.keys())
        prod = c1.selectbox("产品规格", plist)
        qty = c2.number_input("下单数量", min_value=1)
        ddl = c2.date_input("要求交期")
        if st.form_submit_button("确认下单并写回飞书", type="primary"):
            oid = f"ORD-{datetime.now().strftime('%m%d%H%M')}"
            feishu.add(IDS["orders"], {"订单编号": oid, "客户名称": cstm, "产品规格": prod, "订单数量": qty, "承诺交期": ddl, "当前状态": "新建", "已完工数": 0})
            st.rerun()

# --- 3. 计划与采购 [cite: 41, 42] ---
elif menu == "3. 计划与采购":
    st.header("PMC 计划与采购协同")
    unprocessed = st.session_state.orders[st.session_state.orders["当前状态"] == "新建"]
    if not unprocessed.empty:
        sel_oid = st.selectbox("选择订单运行 MRP", unprocessed["订单编号"])
        if st.button("一键拆 BOM 算料并排产"):
            eta = run_mrp_logic(sel_oid)
            st.success(f"排产完成！测算 ETA：{eta}。采购需求已自动同步至飞书。")
            st.rerun()
    else: st.info("目前没有待排产的新订单。")
    
    st.subheader("🛒 采购到货进度 (采购表)")
    st.dataframe(st.session_state.purchases, use_container_width=True)

# --- 5. 车间报工 [cite: 44, 126] ---
elif menu == "5. 车间报工":
    st.header("生产进度实时报工")
    active_jobs = st.session_state.orders[st.session_state.orders["当前状态"].isin(["生产中", "备料中", "可生产"])]
    if not active_jobs.empty:
        sel_oid = st.selectbox("选择工单", active_jobs["订单编号"])
        row = active_jobs[active_jobs["订单编号"]==sel_oid].iloc[0]
        with st.form("prod_report"):
            done = st.number_input("累计产出数量", value=int(row["已完工数"] or 0))
            abnormal = st.selectbox("异常状态", ["无", "停机", "质量异常", "缺料"])
            if st.form_submit_button("提交并重算 ETA"):
                # 滚动重算 ETA
                new_eta = (date.today() + timedelta(days=7)) if done < row["订单数量"] else date.today()
                feishu.update(IDS["orders"], row["_rid"], {
                    "已完工数": done, "异常说明": abnormal, 
                    "当前状态": "生产中" if done < row["订单数量"] else "待出货",
                    "预计发货日": new_eta
                })
                st.rerun()
    else: st.info("暂无在制任务。")

# --- 6. 基础数据 [cite: 48] ---
elif menu == "⚙️ 基础数据":
    st.header("主数据库档案 (读写权限测试)")
    st.subheader("📦 物料与库存状态")
    st.table(st.session_state.inventory)
    st.subheader("🏭 产能基准参数")
    st.table(st.session_state.products)
