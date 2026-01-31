import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime

# 1. Configuración de la página (Debe ser lo primero)
st.set_page_config(page_title="PREFACTURAS - INGENIERIA Y SUPERVISION", layout="wide")

# 2. Conexión a Supabase (Usa st.secrets en producción)
# Por ahora pon tus llaves aquí para probar, luego las movemos a un archivo seguro
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]

@st.cache_resource
def init_connection():
    return create_client(URL, KEY)

supabase = init_connection()

# 3. Título y Métricas Rápidas
st.title("⚡ PROYECTO DE INGENIERIA Y SUPERVISION (DNDS) - SEGUIMIENTO DE PREFACTURAS ")

# Función para cargar datos
def cargar_datos():
    response = supabase.table('prefacturas_pedidos').select("*").order('id').execute()
    df = pd.DataFrame(response.data)
    return df

# Cargar el dataframe
df = cargar_datos()

# --- BLOQUE 1: Convertir texto a fechas reales (Incluyendo Firma DNDS) ---
columnas_fechas = [
    "fecha_elaboracion", 
    "fecha_formato", 
    "fecha_solicitud_modificacion", 
    "fecha_entrega_post_modificacion", 
    "fecha_conciliacion", 
    "fecha_firma_ingenica",
    "fecha_entrega_final_ingenica_central",
    "fecha_firma_dnds",  # <--- AGREGADA OTRA VEZ COMO FECHA
    "fecha_edicion_pedido"  # <--- ¡NUEVA AGREGADA AQUÍ!
]

for col in columnas_fechas:
    if col in df.columns:
        # Convertir a datetime y quitar la hora
        df[col] = pd.to_datetime(df[col], errors='coerce').dt.date
# -------------------------------------------------------------

# --- SECCIÓN DE INDICADORES (Dashboard) ---
if not df.empty:
    col1, col2, col3 = st.columns(3)
    
    # KPI 1: Total de pedidos
    col1.metric("Total Registros", len(df))
    
    # KPI 2: Pendientes de Firma DNDS (donde la fecha es nula)
    # Asumiendo que 'fecha_firma_dnds' es el nombre exacto de la columna
    pendientes_dnds = df['fecha_firma_dnds'].isnull().sum()
    col2.metric("Pendientes Firma DNDS", pendientes_dnds, delta_color="inverse")
    
    # KPI 3: Entregados este mes (Ejemplo)
    # Convertir a datetime si no lo está
    if 'fecha_elaboracion' in df.columns:
        df['fecha_elaboracion'] = pd.to_datetime(df['fecha_elaboracion'])
        mes_actual = datetime.now().month
        entregas_mes = df[df['fecha_elaboracion'].dt.month == mes_actual].shape[0]
        col3.metric(f"Elaborados este Mes ({mes_actual})", entregas_mes)

st.divider()

# --- SECCIÓN DE EDICIÓN ---
st.subheader("📝 Edición de Datos")
st.info("Edita las celdas directamente y presiona 'Guardar Cambios' al final.")

# El editor de datos mágico de Streamlit
df_editado = st.data_editor(
    df,
    num_rows="dynamic",
    hide_index=True,
    column_config={
        # --- 01. SECTOR (Combobox) ---
        "sector": st.column_config.SelectboxColumn(
            "Sector",
            options=["MANAGUA", "NORTE", "OCCIDENTE", "ORIENTE", "SUR"],
            required=False,
            width="medium"
        ),

        # --- 02. SUBSECTOR (Combobox) ---
        "subsector": st.column_config.SelectboxColumn(
            "Subsector",
            options=["MANAGUA DS", "MANAGUA DN", "NORTE", "OCCIDENTE", "ORIENTE", "SUR"],
            required=False,
            width="medium"
        ),

        # --- 03. PERIODO (Combobox con 1Q y 2Q) ---
        "periodo": st.column_config.SelectboxColumn(
            "Periodo",
            options=[
                "ENERO 1Q", "ENERO 2Q", 
                "FEBRERO 1Q", "FEBRERO 2Q", 
                "MARZO 1Q", "MARZO 2Q",
                "ABRIL 1Q", "ABRIL 2Q", 
                "MAYO 1Q", "MAYO 2Q", 
                "JUNIO 1Q", "JUNIO 2Q",
                "JULIO 1Q", "JULIO 2Q", 
                "AGOSTO 1Q", "AGOSTO 2Q", 
                "SEPTIEMBRE 1Q", "SEPTIEMBRE 2Q",
                "OCTUBRE 1Q", "OCTUBRE 2Q", 
                "NOVIEMBRE 1Q", "NOVIEMBRE 2Q", 
                "DICIEMBRE 1Q", "DICIEMBRE 2Q"
            ],
            required=False,
            width="medium"
        ),

        # --- CONFIGURACIÓN DE FECHAS (Calendarios) ---
        "fecha_elaboracion": st.column_config.DateColumn("Fecha Elaboración", format="DD/MM/YYYY", required=False),
        "fecha_formato": st.column_config.DateColumn("Fecha Formato", format="DD/MM/YYYY", required=False),
        "fecha_solicitud_modificacion": st.column_config.DateColumn("Fecha Sol. Modif.", format="DD/MM/YYYY", required=False),
        "fecha_entrega_post_modificacion": st.column_config.DateColumn("Fecha Entrega Post Modif.", format="DD/MM/YYYY", required=False),
        "fecha_conciliacion": st.column_config.DateColumn("Fecha Conciliación", format="DD/MM/YYYY", required=False),
        "fecha_firma_ingenica": st.column_config.DateColumn("Firma Ingenica", format="DD/MM/YYYY", required=False),
        "fecha_entrega_final_ingenica_central": st.column_config.DateColumn("Entrega Final Central", format="DD/MM/YYYY", required=False),
        
        # --- FIRMA DNDS (Calendario) ---
        "fecha_firma_dnds": st.column_config.DateColumn(
            "Firma DNDS", 
            format="DD/MM/YYYY", 
            required=False,
            help="Si está vacía, se considera PENDIENTE"
        ),

        # --- ¡NUEVA COLUMNA CON CALENDARIO! ---
        "fecha_edicion_pedido": st.column_config.DateColumn(
            "Fecha Edición Pedido",
            format="DD/MM/YYYY",
            required=False
        ),

        # --- ÁREA (Ya lo tenías) ---
        "area": st.column_config.SelectboxColumn(
            "Área", 
            options=["MANTENIMIENTO", "DESARROLLO", "PROYECTOS", "PNESER", "CAMPAÑA"]
        ),

        # --- COLUMNAS TÉCNICAS (Ocultas/Bloqueadas) ---
        "id": st.column_config.Column(disabled=True, width="small"),
        "created_at": st.column_config.Column(disabled=True, width="small"),
    },
    use_container_width=True
)
# --- Botón de Guardar (Versión Divide y Vencerás) ---
if st.button("Guardar Cambios en Supabase"):
    try:
        # 1. Preparar los datos
        datos_a_enviar = df_editado.copy()

        # 2. CONVERSIÓN DE FECHAS (Tu traductor que ya funciona)
        columnas_fechas_guardar = [
            "fecha_elaboracion", "fecha_formato", "fecha_solicitud_modificacion", 
            "fecha_entrega_post_modificacion", "fecha_conciliacion", 
            "fecha_firma_ingenica", "fecha_entrega_final_ingenica_central",
            "fecha_firma_dnds", "fecha_edicion_pedido"
        ]

        for col in columnas_fechas_guardar:
            if col in datos_a_enviar.columns:
                datos_a_enviar[col] = pd.to_datetime(datos_a_enviar[col], dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')
                datos_a_enviar[col] = datos_a_enviar[col].replace(['nan', 'NaT', 'None', '<NA>'], None)
                datos_a_enviar[col] = datos_a_enviar[col].where(pd.notnull(datos_a_enviar[col]), None)

        # 3. Convertir a lista de diccionarios
        registros = datos_a_enviar.to_dict('records')
        
        # 4. LIMPIEZA Y SEPARACIÓN (Aquí está el truco nuevo)
        registros_actualizar = [] # Filas viejas (tienen ID)
        registros_crear = []      # Filas nuevas (no tienen ID)

        for reg in registros:
            nuevo_reg = reg.copy()
            id_val = nuevo_reg.get('id')
            
            # Limpiamos created_at si está vacío
            if pd.isna(nuevo_reg.get('created_at')):
                if 'created_at' in nuevo_reg: del nuevo_reg['created_at']

            # CLASIFICACIÓN: ¿Es nuevo o viejo?
            if id_val is None or pd.isna(id_val) or str(id_val).strip() == "":
                # ES NUEVO: Borramos el ID para que Supabase lo invente
                if 'id' in nuevo_reg: del nuevo_reg['id']
                registros_crear.append(nuevo_reg)
            else:
                # ES VIEJO: Lo dejamos tal cual para actualizar
                registros_actualizar.append(nuevo_reg)

        # 5. ENVIAR POR SEPARADO
        # A) Actualizamos los existentes (Upsert)
        if len(registros_actualizar) > 0:
            supabase.table('prefacturas_pedidos').upsert(registros_actualizar).execute()
            
        # B) Insertamos los nuevos (Insert)
        if len(registros_crear) > 0:
            supabase.table('prefacturas_pedidos').insert(registros_crear).execute()
        
        # 6. Éxito
        st.success("¡Cambios guardados correctamente!")
        st.balloons()
        
        # Recargar para ver los nuevos IDs asignados
        # st.rerun() 

    except Exception as e:
        st.error(f"Error al guardar: {e}")
        
# --- EXPORTAR DATOS ---
st.divider()
csv = df_editado.to_csv(index=False).encode('utf-8')
st.download_button(
    label="📥 Descargar Tabla (CSV)",
    data=csv,
    file_name='control_entregas_ingenica.csv',
    mime='text/csv',

)



















