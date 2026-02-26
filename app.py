import streamlit as st
import pandas as pd
import math
from datetime import date, timedelta
import requests
import io
import random

# ==========================================
# 飞书多维表格云端连接器 (功能增强版)
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

    def get_records(self, table_id, default_columns):
        if not table_id.startswith("tbl"):
            return pd.DataFrame(columns=default_columns + ["_record_id"])
            
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records"
        headers = {"Authorization": f"Bearer {self.token}"}
        res = requests.get(url, headers=headers)
        items = res.json().get("data", {}).get("items", [])
        
        if items:
            data_list = []
            for i in items:
                row = i['fields']
                row['_record_id'] = i['record_id']
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
        res = requests.post(url, headers=headers, json={"fields": formatted_fields})
        return res.json()

    def update_record(self, table_id, record_id, fields):
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{record_id}"
        headers = {"Authorization": f"Bearer {self.token}"}
        formatted_fields = {}
        for k, v in fields.items():
            if isinstance(v, (date, pd.Timestamp)):
                formatted_fields[k] = int(pd.to_datetime(v).timestamp() * 1000)
            else:
                formatted_fields[k] = v
        res = requests.patch(url, headers=headers, json={"fields": formatted_fields})
        return res.json()

# ==========================================
# 0. 初始化配置与数据拉取
# ==========================================
st.set_page_config(page_title="手搓跟单系统", page_icon="🚀", layout="wide")

# [cite_start]真实表ID (从你提供的txt文件提取) [cite: 1]
IDS = {
    "orders": "tblvMUMfyVcRgxnF",
    "materials": "tbl5HsYZEDqQiVvM",
    "products": "tbl7Ecj7t3FAQ2Cf",
    "inventory": "tbl69MGcduldUpt9",
    "purchases": "tblpPk2pb3Hw9xQF"
}

@st.cache_resource
def get_handler():
    return FeishuBitable()

fs = get_handler()

# 加载数据到 Session State
def reload_data():
    st.session_state.orders = fs.get_records(IDS["orders"], ["订单编号", "客户名称", "产品规格", "订单数量", "已完工数", "当前状态", "承诺交期"])
    st.session_state.products = fs.get_records(IDS["products"], ["产品规格", "标准日产能", "包装缓冲天数"])

if 'orders' not in st.session_state:
    reload_data()

# ==========================================
# 侧边栏菜单与测试工具
# ==========================================
menu = st.sidebar.radio("业务模块", ["📊 看板", "📝 销售下单", "🔧 车间报工"])

st.sidebar.markdown("---")
st.sidebar.subheader("🛠️ 开发者测试工具")

# 功能：一键生成模拟订单并同步飞书
if st.sidebar.button("🚀 一键生成 3 条模拟订单"):
    test_customers = ["顺丰速运", "华为终端", "格力电器", "美团外卖"]
    test_products = ["漏电保护插头-标准款", "精密冲压端子-B型"]
    
    with st.spinner("正在同步至飞书..."):
        for _ in range(3):
            random_oid = f"TEST-{random.randint(1000, 9999)}"
            new_row = {
                "订单编号": random_oid,
                "客户名称": random.choice(test_customers),
                "产品规格": random.choice(test_products) if not st.session_state.products.empty else "默认规格",
                "订单数量": random.randint(100, 1000),
                "已完工数": 0,
                "当前状态": "新建",
                "承诺交期": date.today() + timedelta(days=random.randint(7, 30))
            }
            fs.add_record(IDS["orders"], new_row)
        
        st.sidebar.success("模拟订单已成功写入飞书！")
        reload_data() # 刷新本地数据
        st.rerun()

# 保持之前的 Excel 模板功能
if st.sidebar.button("📥 下载飞书导入模板"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        pd.DataFrame([["MAT-001", "阻燃外壳", 3, 1000]], columns=["物料编码", "物料名称", "采购周期(天)", "最小采购量"]).to_excel(writer, sheet_name="物料表", index=False)
        pd.DataFrame([["漏电保护插头-标准款", 200, 1]], columns=["产品规格", "标准日产能", "包装缓冲天数"]).to_excel(writer, sheet_name="产品表", index=False)
    output.seek(0)
    st.sidebar.download_button(label="点击下载", data=output, file_name="飞书模板.xlsx")

# ==========================================
# 页面模块实现
# ==========================================
if menu == "📊 看板":
    st.header("全流程订单看板")
    if not st.session_state.orders.empty:
        st.dataframe(st.session_state.orders.drop(columns=["_record_id"], errors='ignore'), use_container_width=True)
    else:
        st.info("当前订单表为空，请使用侧边栏工具生成测试数据。")

elif menu == "📝 销售下单":
    st.header("新订单录入")
    with st.form("manual_order"):
        c1, c2 = st.columns(2)
        cstm = c1.text_input("客户名称")
        prod = c1.selectbox("产品规格", st.session_state.products["产品规格"].tolist() if not st.session_state.products.empty else ["请先在产品表添加规格"])
        qty = c2.number_input("数量", min_value=1)
        ddl = c2.date_input("承诺交期")
        if st.form_submit_button("确认下单"):
            oid = f"ORD-{date.today().strftime('%m%d%H%M')}"
            fields = {"订单编号": oid, "客户名称": cstm, "产品规格": prod, "订单数量": qty, "承诺交期": ddl, "当前状态": "新建", "已完工数": 0}
            res = fs.add_record(IDS["orders"], fields)
            if res.get("code") == 0:
                st.success(f"订单 {oid} 已同步至飞书！")
                reload_data()
            else:
                st.error(f"同步失败: {res.get('msg')}")

elif menu == "🔧 车间报工":
    st.header("生产进度上报")
    if not st.session_state.orders.empty:
        # 只显示未完成的订单
        active_orders = st.session_state.orders[st.session_state.orders["当前状态"] != "已出货"]
        sel_oid = st.selectbox("选择订单", active_orders["订单编号"])
        order_row = st.session_state.orders[st.session_state.orders["订单编号"] == sel_oid].iloc[0]
        
        with st.form("report_form"):
            new_qty = st.number_input("累计已完工数", value=int(order_row["已完工数"]))
            new_status = st.selectbox("状态修改", ["新建", "生产中", "待出货", "已出货"], 
                                    index=["新建", "生产中", "待出货", "已出货"].index(order_row["当前状态"]))
            if st.form_submit_button("提交报工"):
                res = fs.update_record(IDS["orders"], order_row["_record_id"], {"已完工数": new_qty, "当前状态": new_status})
                if res.get("code") == 0:
                    st.success("报工成功！飞书已更新。")
                    reload_data()
                    st.rerun()
                else:
                    st.error("飞书同步失败")
