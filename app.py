import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime

# 1. Configuración de la página (Debe ser lo primero)
st.set_page_config(page_title="PREFACTURAS INGENICA", layout="wide")

# 2. Conexión a Supabase (Usa st.secrets en producción)
# Por ahora pon tus llaves aquí para probar, luego las movemos a un archivo seguro
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]

@st.cache_resource
def init_connection():
    return create_client(URL, KEY)

supabase = init_connection()

# 3. Título y Métricas Rápidas
st.title("⚡ PREFACTURAS - INGENICA")

# Función para cargar datos
def cargar_datos():
    response = supabase.table('prefacturas_pedidos').select("*").order('id').execute()
    df = pd.DataFrame(response.data)
    return df

# Cargar el dataframe
df = cargar_datos()

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
# num_rows="dynamic" permite agregar nuevas filas
df_editado = st.data_editor(
    df, 
    num_rows="dynamic", 
    hide_index=True,
    column_config={
        "fecha_elaboracion": st.column_config.DateColumn("Fecha Elaboración"),
        "fecha_firma_dnds": st.column_config.DateColumn("Firma DNDS"),
        "area": st.column_config.SelectboxColumn("Área", options=["MANTENIMIENTO", "DESARROLLO", "PROYECTOS", "PNESER"]),
        # Ocultamos columnas técnicas que no deben tocar
        "id": st.column_config.Column(disabled=True),
        "created_at": st.column_config.Column(disabled=True),
    },
    use_container_width=True
)

# --- Botón de Guardar ---
if st.button("Guardar Cambios en Supabase"):
    try:
        # 1. Creamos una copia de los datos para prepararlos
        datos_a_enviar = df_editado.copy()

        # 2. TRUCO DE MAGIA: Convertimos todas las fechas a texto (String)
        # Esto evita el error "Timestamp is not JSON serializable"
        for col in datos_a_enviar.select_dtypes(include=['datetime', 'datetimetz']).columns:
            datos_a_enviar[col] = datos_a_enviar[col].astype(str)
            # Limpiamos errores de fechas vacías (NaT)
            datos_a_enviar[col] = datos_a_enviar[col].replace('NaT', None)

        # 3. Convertimos a lista de diccionarios y enviamos
        registros = datos_a_enviar.to_dict('records')
        
        # Enviamos a Supabase
        response = supabase.table('prefacturas_pedidos').upsert(registros).execute()
        
        # 4. Mensaje de éxito
        st.success("¡Cambios guardados correctamente en la nube!")
        st.balloons()
        
        # Opcional: Recargar la página tras unos segundos para ver cambios
        # st.experimental_rerun() 

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






