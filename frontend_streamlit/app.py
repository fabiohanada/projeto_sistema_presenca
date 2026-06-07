import streamlit as st
import pandas as pd
from datetime import datetime
import io
import re
import numpy as np
from PIL import Image
import easyocr
import cv2  # <--- ADICIONADO PARA O FILTRO
from supabase import create_client, Client

st.set_page_config(layout="wide")

# --- CONEXÃO COM O BANCO DE DADOS ---
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"].strip().rstrip("/")
    if "/rest/v1" in url: url = url.split("/rest/v1")[0]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# Funções Auxiliares
def get_alunos():
    try: return supabase.table("alunos").select("*").execute().data or []
    except: return []

def get_aulas():
    try: return supabase.table("aulas").select("*").order("data").execute().data or []
    except: return []

def get_presencas():
    try: return supabase.table("presencas").select("*").execute().data or []
    except: return []

@st.cache_resource
def carregar_ia():
    return easyocr.Reader(['pt'], gpu=False)

leitor_ia = carregar_ia()
alunos_db = get_alunos()
aulas_db = get_aulas()
presencas_db = get_presencas()

# --- TOPO: LAYOUT ORIGINAL ---
st.title("PROFESSOR THIAGO")
st.subheader("Sistema de Presença Automática")
st.markdown("---")

tab_file, tab_cam = st.tabs(["📁 Ficheiro", "📷 Câmara"])
foto_documento = None

with tab_file:
    foto_upload = st.file_uploader("Envie a foto do documento", type=["png", "jpg", "jpeg"])
    if foto_upload: foto_documento = foto_upload

with tab_cam:
    if st.toggle("Ligar Câmara"):
        foto_camera = st.camera_input("Posicione o documento")
        if foto_camera: foto_documento = foto_camera

# Processamento com melhoria de contraste (Filtro CV2)
if foto_documento:
    if st.button("🚀 Processar Documento Capturado", type="primary"):
        with st.spinner("🤖 IA a ler..."):
            # FILTRO DE IMAGEM ADICIONADO
            img_raw = np.array(Image.open(foto_documento).convert('L'))
            _, img = cv2.threshold(img_raw, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            res = leitor_ia.readtext(img, detail=0)
            texto = " ".join(res).upper()
            match_d = re.search(r'\b\d{2}/\d{2}/\d{4}\b', texto)
            match_s = re.search(r'\b\d{15}\b', texto.replace(" ", ""))
            
            novo_aluno = {
                "nome": "ALUNO IA", 
                "nasc": match_d.group(0) if match_d else "NÃO DETECTADO", 
                "sus": match_s.group(0) if match_s else "NÃO DETECTADO", 
                "rg": "NÃO DETECTADO", # Campo RG para IA
                "genero": "-", 
                "prontuario": "GERAR"
            }
            supabase.table("alunos").insert(novo_aluno).execute()
            st.success("✅ Aluno processado com sucesso!")
            st.rerun()
else:
    st.info("A aguardar captura...")

# --- 2. CADASTRO MANUAL ---
with st.expander("👤 Cadastro Manual de Aluno"):
    with st.form("form_manual", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        nome_m = c1.text_input("Nome")
        rg_m = c2.text_input("RG") 
        nasc_m = c2.date_input("Nascimento", value=None, min_value=datetime(1900, 1, 1), format="DD/MM/YYYY")
        gen_m = c3.selectbox("Gênero", ["MASCULINO", "FEMININO", "OUTRO"])
        sus_m = c1.text_input("Cartão SUS")
        pront_m = c2.text_input("Prontuário")
        
        if c3.form_submit_button("CADASTRAR"):
            if nasc_m is None: st.error("Selecione a data de nascimento.")
            else:
                supabase.table("alunos").insert({
                    "nome": nome_m.upper(), "rg": rg_m, "nasc": nasc_m.strftime('%d/%m/%Y'), 
                    "sus": sus_m, "genero": gen_m, "prontuario": pront_m
                }).execute()
                st.rerun()

# --- 3. INSERÇÃO DE AULA ---
with st.expander("✏️ Inserir Nova Aula"):
    with st.form("form_aula", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        tema = c1.text_input("Tema")
        data_aula = c2.date_input("Data", format="DD/MM/YYYY")
        qtd = c3.number_input("Presentes", step=1, value=0)
        if st.form_submit_button("INSERIR AULA"):
            supabase.table("aulas").insert({"tema": tema.upper(), "data": data_aula.strftime('%d/%m/%Y'), "qtd": qtd}).execute()
            st.rerun()

# --- 3.5 GERENCIAR AULAS ---
with st.expander("⚙️ Gerenciar Aulas Criadas (Editar / Excluir)"):
    if aulas_db:
        opcoes_aulas = {f"{a['data']} - {a['tema']}": a for a in aulas_db}
        aula_selecionada = st.selectbox("Selecione a Aula que deseja modificar:", list(opcoes_aulas.keys()))
        aula_dados = opcoes_aulas[aula_selecionada]
        c1, c2, c3 = st.columns(3)
        novo_tema_edit = c1.text_input("Editar Tema", value=aula_dados['tema'], key="tema_edit")
        try: data_obj = datetime.strptime(aula_dados['data'], '%d/%m/%Y')
        except: data_obj = datetime.today()
        nova_data_edit = c2.date_input("Editar Data", value=data_obj, format="DD/MM/YYYY", key="data_edit")
        nova_qtd_edit = c3.number_input("Editar Presentes", value=int(aula_dados.get('qtd', 0)), step=1, key="qtd_edit")
        
        if st.button("💾 Salvar Edição da Aula", type="primary"):
            supabase.table("aulas").update({"tema": novo_tema_edit.upper(), "data": nova_data_edit.strftime('%d/%m/%Y'), "qtd": nova_qtd_edit}).eq("id", aula_dados['id']).execute()
            st.rerun()
            
        if st.button("❌ Excluir Aula"):
            supabase.table("aulas").delete().eq("id", aula_dados['id']).execute()
            st.rerun()

# --- 4. TABELA DE ALUNOS ---
st.markdown("### 📋 Tabela de Alunos Presentes")

colunas_principais = ["NOME", "RG", "DATA NASCIMENTO", "CARTAO SUS", "GENERO", "PRONTUARIO"]
config_colunas = {
    "NOME": st.column_config.TextColumn("NOME"),
    "RG": st.column_config.TextColumn("RG"),
    "DATA NASCIMENTO": st.column_config.TextColumn("DATA NASCIMENTO"),
    "CARTAO SUS": st.column_config.TextColumn("CARTAO SUS"),
    "GENERO": st.column_config.TextColumn("GENERO"),
    "PRONTUARIO": st.column_config.TextColumn("PRONTUARIO"),
    "EXCLUIR": st.column_config.CheckboxColumn("❌ EXCLUIR", default=False)
}

presencas_dict = {(p['id_aluno'], p['id_aula']): p['presente'] for p in presencas_db}
colunas_aulas_map = []

for i, aula in enumerate(aulas_db):
    col_nome = f"{aula['data']} | {aula['tema'].upper()} ({aula.get('qtd', 0)} Presentes)" + (" " * i)
    colunas_principais.append(col_nome)
    colunas_aulas_map.append((aula['id'], col_nome))
    config_colunas[col_nome] = st.column_config.CheckboxColumn(col_nome, default=False)

colunas_principais.append("EXCLUIR")
linhas_tabela = []
mapping_linhas_alunos = {}

for i, aluno in enumerate(alunos_db):
    linha_aluno = [aluno["nome"], aluno.get("rg", ""), aluno["nasc"], aluno["sus"], aluno["genero"], aluno["prontuario"]]
    mapping_linhas_alunos[i] = aluno["id"]
    for id_aula, col_nome in colunas_aulas_map:
        linha_aluno.append(presencas_dict.get((aluno['id'], id_aula), False))
    linha_aluno.append(False) 
    linhas_tabela.append(linha_aluno)

df_edit_display = pd.DataFrame(linhas_tabela, columns=colunas_principais)
for col in colunas_principais[6:]: df_edit_display[col] = df_edit_display[col].astype(bool)
df_edit_display["EXCLUIR"] = df_edit_display["EXCLUIR"].astype(bool)

df_editado = st.data_editor(df_edit_display, width='stretch', hide_index=True, column_config=config_colunas)

if st.button("💾 SALVAR TODAS ALTERAÇÕES", type="primary"):
    with st.spinner("A salvar..."):
        for idx, row in df_editado.iterrows():
            id_al = mapping_linhas_alunos[idx]
            
            # A última coluna do df_editado é sempre a de EXCLUIR
            # row.iloc[-1] pega o último valor da linha, não importa o nome da coluna
            quer_excluir = row.iloc[-1] 
            
            # Removemos NaN convertendo para string vazia ou None
            def clean(val):
                if pd.isna(val) or val is None: return ""
                return str(val)

            if quer_excluir == True: 
                supabase.table("alunos").delete().eq("id", id_al).execute()
            else:
                supabase.table("alunos").update({
                    "nome": clean(row["NOME"]),
                    "rg": clean(row["RG"]),
                    "nasc": clean(row["DATA NASCIMENTO"]),
                    "sus": clean(row["CARTAO SUS"]),
                    "genero": clean(row["GENERO"]),
                    "prontuario": clean(row["PRONTUARIO"])
                }).eq("id", id_al).execute()
                
                # Salva presenças (excluímos a última coluna da contagem)
                for id_aula, col_nome in colunas_aulas_map:
                    val_check = row[col_nome]
                    supabase.table("presencas").upsert({
                        "id_aluno": id_al, 
                        "id_aula": id_aula, 
                        "presente": bool(val_check) if not pd.isna(val_check) else False
                    }).execute()
        st.toast("✅ Base de dados atualizada!")
        st.rerun()

# --- 5. EXPORTAÇÃO ---
with st.expander("📥 Exportar Dados"):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer: 
        df_export = df_editado.drop(columns=["EXCLUIR"])
        df_export.to_excel(writer, index=False, sheet_name='Presencas')
    st.download_button("BAIXAR EXCEL", data=buffer.getvalue(), file_name="Presencas.xlsx", mime="application/vnd.ms-excel")