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

tab_file, tab_cam = st.tabs(["📁 Ficheiro", "📷 Câmera"])
foto_documento = None

with tab_file:
    foto_upload = st.file_uploader("Envie a foto do documento", type=["png", "jpg", "jpeg"])
    if foto_upload: foto_documento = foto_upload

with tab_cam:
    if st.toggle("Ligar Câmara"):
        foto_camera = st.camera_input("Posicione o documento")
        if foto_camera: foto_documento = foto_camera

# --- NO SEU BLOCO DE PROCESSAMENTO ---
if foto_documento:
    if st.button("🚀 Processar com Recorte Inteligente (ROI)"):
        with st.spinner("Analisando zonas do cartão..."):
            # Converte a imagem para o formato que o OpenCV entende
            img = np.array(Image.open(foto_documento).convert('RGB'))
            
            # Altura e Largura da imagem
            h, w, _ = img.shape
            
            # --- DEFINIÇÃO DAS ZONAS (ROI) ---
            # [y_inicial:y_final, x_inicial:x_final]
            # Estas coordenadas foram estimadas para um cartão SUS padrão
            roi_nome = img[int(h*0.20):int(h*0.45), int(w*0.05):int(w*0.95)] # Topo (Nome)
            roi_sus  = img[int(h*0.65):int(h*0.85), int(w*0.10):int(w*0.90)] # Base (SUS)
            
            # Função para ler cada zona
            def extrair_texto(crop):
                # O EasyOCR lê melhor imagens em escala de cinza
                gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
                # O parâmetro 'contrast_ths' ajuda em fotos com pouca luz
                res = leitor_ia.readtext(gray, detail=0, contrast_ths=0.2)
                return " ".join(res).strip()

            # Processamento
            nome_detectado = extrair_texto(roi_nome)
            sus_detectado = extrair_texto(roi_sus)
            
            # --- FEEDBACK VISUAL ---
            # Isto é CRUCIAL: se os cortes saírem vazios, ajusta os valores 'h*' acima
            st.write("### Conferência dos Recortes:")
            st.image([roi_nome, roi_sus], caption=["Corte Nome", "Corte SUS"])
            
            # Exibe o resultado
            st.success(f"**Nome:** {nome_detectado}")
            st.success(f"**SUS:** {sus_detectado}")
            
            if st.button("💾 Confirmar e Salvar Dados"):
                # 1. Preparar os dados
                dados_para_inserir = {
                    "nome": nome_detectado.strip(),
                    "sus": sus_detectado.strip(),
                    "nasc": "01/01/2000", # Placeholder
                    "rg": "NÃO DETECTADO",
                    "genero": "-",
                    "prontuario": "GERAR"
                }
                
                # 2. Tentar inserir com verificação de erro
                try:
                    # Tenta a inserção e guarda a resposta
                    response = supabase.table("alunos").insert(dados_para_inserir).execute()
                    
                    # Se chegarmos aqui sem erro, funcionou
                    st.success("✅ Aluno inserido com sucesso na base de dados!")
                    st.balloons()
                    
                except Exception as e:
                    # Se der erro, vamos mostrar exatamente qual é o erro
                    st.error("❌ ERRO AO INSERIR NO SUPABASE:")
                    st.code(e)
                    st.warning("Dica: Verifique se o nome da tabela no Supabase é exatamente 'alunos' (tudo minúsculo).")
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