import streamlit as st
import pandas as pd
import math
from datetime import date, timedelta, datetime
import requests
import io
import random

# ==========================================
# 1. 飞书多维表格引擎 (带自动报错与日期转换)
# ==========================================
class FeishuBitable:
    def __init__(self):
        try:
            self.app_id = st.secrets["feishu"]["app_id"]
            self.app_secret = st.secrets["feishu"]["app_secret"]
            self.app_token = st.secrets["feishu"]["app_token"]
            self.token = self._get_token()
        except Exception as e:
            st.error(f"❌ 飞书密钥配置错误！请检查 Streamlit Secrets。错误详情: {e}")
            st.stop()

    def _get_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        res = requests.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret})
        return res.json().get("tenant_access_token")

    def _format_date(self, ts):
        if pd.isna(ts) or not ts: return None
        try: return datetime.fromtimestamp(int(ts)/1000).date()
        except: return None

    def get_records(self, table_id, cols):
        """拉取数据并处理列名映射 """
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records?page_size=100"
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(url, headers=headers).json()
        
        if response.get("code") != 0:
            st.warning(f"⚠️ 表 {table_id} 读取异常: {response.get('msg')}")
            return pd.DataFrame(columns=cols + ["_record_id"])

        items = response.get("data", {}).get("items", [])
        if items:
            df = pd.DataFrame([dict(i['fields'], _record_id=i['record_id']) for i in items])
            # 日期清洗 [cite: 1, 94, 95]
            for c in df.columns:
                if any(x in c for x in ['日期', '交期', '发货', '到料', '到货']):
                    df[c] = df[c].apply(self._format_date)
            # 补齐缺失列
            for c in cols:
                if c not in df.columns: df[c] = None
            return df
        return pd.DataFrame(columns=cols + ["_record_id"])

    def add_record(self, table_id, fields):
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records"
        formatted = {k: (int(pd.to_datetime(v).timestamp()*1000) if isinstance(v, (date, datetime)) else v) for k, v in fields.items()}
        res = requests.post(url, headers={"Authorization": f"Bearer {self.token}"}, json={"fields": formatted}).json()
        if res.get("code") != 0: st.error(f"新增失败: {res.get('msg')}")
        return res

    def update_record(self, table_id, rid, fields):
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{rid}"
        formatted = {k: (int(pd.to_datetime(v).timestamp()*1000) if isinstance(v, (date, datetime)) else v) for k, v in fields.items()}
        res = requests.patch(url, headers={"Authorization": f"Bearer {self.token}"}, json={"fields": formatted}).json()
        if res.get("code") != 0: st.error(f"更新失败: {res.get('msg')}")
        return res

# ==========================================
# 2. 全自动数据同步与配置
# ==========================================
st.set_page_config(page_title="跟单协同系统 PRO", page_icon="🏭", layout="wide")
fs = FeishuBitable()

# 真实表 ID (请根据你的飞书 URL 确认)
IDS = {
    "orders": "tblvMUMfyVcRgxnF", 
    "materials": "tbl5HsYZEDqQiVvM",
    "products": "tbl7Ecj7t3FAQ2Cf", 
    "inventory": "tbl69MGcduldUpt9",
    "purchases": "tblpPk2pb3Hw9xQF"
}

# 自动刷新逻辑：不再需要手动按钮
def auto_reload():
    st.session_state.orders = fs.get_records(IDS["orders"], ["订单编号", "客户名称", "产品规格", "订单数量", "已完工数", "承诺交期", "预计发货日", "最晚到料日", "当前状态", "异常说明", "收款情况"])
    st.session_state.materials = fs.get_records(IDS["materials"], ["物料编码", "物料名称", "采购周期(天)", "最小采购量"])
    st.session_state.inventory = fs.get_records(IDS["inventory"], ["物料编码", "现存量", "预留量", "安全库存"])
    st.session_state.products = fs.get_records(IDS["products"], ["产品规格", "标准日产能", "包装缓冲天数"])
    st.session_state.purchases = fs.get_records(IDS["purchases"], ["采购单号", "关联订单", "物料编码", "采购数量", "承诺到货日", "状态"])

# 脚本每次运行都会自动执行加载
auto_reload()

# 文档中要求的 BOM 结构 [cite: 1, 56, 76]
BOM_MASTER = {
    "漏电保护插头-标准款": {"MAT-001": 1, "MAT-002": 3, "MAT-003": 1},
    "精密冲压端子-B型": {"MAT-002": 1, "MAT-001": 0.5}
}

# ==========================================
# 3. 核心计算逻辑 (MRP & ETA) [cite: 1, 88-104]
# ==========================================
def run_mrp_engine(oid):
    order = st.session_state.orders[st.session_state.orders["订单编号"] == oid].iloc[0]
    bom = BOM_MASTER.get(order["产品规格"], {})
    latest_arrival = date.today()
    has_shortage = False
    
    for m_code, unit_qty in bom.items():
        req = order["订单数量"] * unit_qty 
        # 库存校验逻辑 
        try:
            inv = st.session_state.inventory[st.session_state.inventory["物料编码"] == m_code].iloc[0]
            avail = (inv["现存量"] or 0) - (inv["预留量"] or 0) - (inv["安全库存"] or 0)
        except:
            avail = 0
        
        gap = max(0, req - avail)
        if gap > 0:
            has_shortage = True
            m_info = st.session_state.materials[st.session_state.materials["物料编码"]==m_code].iloc[0]
            arr_date = date.today() + timedelta(days=int(m_info["采购周期(天)"] or 7))
            latest_arrival = max(latest_arrival, arr_date)
            # 生成采购单 [cite: 1, 58, 82]
            fs.add_record(IDS["purchases"], {
                "采购单号": f"PO-{oid}-{m_code}", "关联订单": oid, "物料编码": m_code,
                "采购数量": max(gap, m_info["最小采购量"] or 0), "承诺到货日": arr_date, "状态": "采购中"
            })
    
    # ETA 滚动预测 [cite: 1, 100-104]
    try:
        prod_info = st.session_state.products[st.session_state.products["产品规格"] == order["产品规格"]].iloc[0]
        days_needed = math.ceil(order["订单数量"] / (prod_info["标准日产能"] or 100))
        eta = latest_arrival + timedelta(days=days_needed + int(prod_info["包装缓冲天数"] or 1))
    except:
        eta = latest_arrival + timedelta(days=7)
    
    # 写回飞书
    fs.update_record(IDS["orders"], order["_record_id"], {
        "当前状态": "备料中" if has_shortage else "可生产",
        "预计发货日": eta, "最晚到料日": latest_arrival
    })
    return eta

# ==========================================
# 4. 业务界面实现
# ==========================================
st.sidebar.title("🏭 跟单云协同系统")
menu = st.sidebar.radio("核心业务模块", ["1. 首页看板", "2. 销售与订单", "3. 计划与采购", "4. 仓储物流", "5. 生产车间", "⚙️ 基础数据"])

# 侧边栏测试工具 [cite: 1, 107]
st.sidebar.markdown("---")
if st.sidebar.button("🚀 随机生成 3 条订单并同步飞书"):
    with st.spinner("数据写入中..."):
        for _ in range(3):
            fs.add_record(IDS["orders"], {
                "订单编号": f"TEST-{random.randint(100,999)}", "客户名称": random.choice(["华为", "比亚迪", "格力"]),
                "产品规格": random.choice(list(BOM_MASTER.keys())), "订单数量": random.randint(200,1000),
                "承诺交期": date.today() + timedelta(days=15), "当前状态": "新建", "已完工数": 0, "收款情况": "未收款"
            })
        st.rerun()

# --- 1. 首页看板 [cite: 1, 105, 106] ---
if menu == "1. 首页看板":
    st.header("📊 管理驾驶舱")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("待处理订单", len(st.session_state.orders[st.session_state.orders["当前状态"]=="新建"]))
    c2.metric("缺料备料中", len(st.session_state.orders[st.session_state.orders["当前状态"]=="备料中"]))
    c3.metric("在制异常", len(st.session_state.orders[st.session_state.orders["异常说明"]!="无"]))
    c4.metric("交期风险", len(st.session_state.orders[(st.session_state.orders["预计发货日"] > st.session_state.orders["承诺交期"]).fillna(False)]))
    
    st.subheader("📋 实时订单台账")
    st.dataframe(st.session_state.orders.drop(columns=["_record_id"], errors='ignore'), use_container_width=True)

# --- 2. 销售与订单 [cite: 1, 71, 72] ---
elif menu == "2. 销售与订单":
    st.header("销售订单中心")
    tab1, tab2 = st.tabs(["📝 录入新订单", "🔍 订单追踪"])
    with tab1:
        with st.form("manual_order"):
            c1, c2 = st.columns(2)
            cstm = c1.text_input("客户名称")
            # 自动加载产品规格 [cite: 1, 75]
            plist = st.session_state.products["产品规格"].tolist() if not st.session_state.products.empty else list(BOM_MASTER.keys())
            prod = c1.selectbox("产品规格", plist)
            qty = c2.number_input("订单数量", min_value=1)
            ddl = c2.date_input("交期要求")
            if st.form_submit_button("确认提交", type="primary"):
                oid = f"ORD-{datetime.now().strftime('%m%d%H%M')}"
                fs.add_record(IDS["orders"], {"订单编号": oid, "客户名称": cstm, "产品规格": prod, "订单数量": qty, "承诺交期": ddl, "当前状态": "新建", "已完工数": 0, "收款情况": "未收款"})
                st.rerun()
    with tab2:
        st.dataframe(st.session_state.orders)

# --- 3. 计划与采购 [cite: 1, 88-96] ---
elif menu == "3. 计划与采购":
    st.header("PMC 计划与采购协同")
    unprocessed = st.session_state.orders[st.session_state.orders["当前状态"] == "新建"]
    if not unprocessed.empty:
        sel_oid = st.selectbox("选择订单运行 MRP", unprocessed["订单编号"])
        if st.button("执行 MRP 排产并同步飞书"):
            eta = run_mrp_engine(sel_oid)
            st.success(f"排产完成！系统测算 ETA：{eta}，采购单已生成。")
            st.rerun()
    else:
        st.info("没有待算的新订单。")
    st.subheader("采购到货进度")
    st.dataframe(st.session_state.purchases)

# --- 5. 生产车间 [cite: 1, 126-128] ---
elif menu == "5. 生产车间":
    st.header("车间生产报工")
    active_jobs = st.session_state.orders[st.session_state.orders["当前状态"].isin(["备料中", "生产中", "可生产"])]
    if not active_jobs.empty:
        sel_oid = st.selectbox("选择工单", active_jobs["订单编号"])
        row = active_jobs[active_jobs["订单编号"]==sel_oid].iloc[0]
        with st.form("prod_rp"):
            done = st.number_input("累计完工数", value=int(row["已完工数"] or 0))
            abn = st.selectbox("异常提报", ["无", "设备故障", "缺料", "质量问题"])
            if st.form_submit_button("提交报工 (更新飞书 ETA)"):
                # 重新计算 ETA [cite: 1, 100]
                new_eta = (date.today() + timedelta(days=7)) if done < row["订单数量"] else date.today()
                fs.update_record(IDS["orders"], row["_record_id"], {
                    "已完工数": done, "异常说明": abn, "当前状态": "生产中" if done < row["订单数量"] else "待出货",
                    "预计发货日": new_eta
                })
                st.rerun()
    else:
        st.info("暂无生产任务。")

# --- 6. 基础数据 [cite: 1, 74-80] ---
elif menu == "⚙️ 基础数据":
    st.header("主数据库档案")
    st.subheader("物料信息")
    st.table(st.session_state.materials)
    st.subheader("产品产能参数 [cite: 1, 77]")
    st.table(st.session_state.products)
