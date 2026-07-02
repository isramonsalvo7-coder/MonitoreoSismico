import time
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go  # <-- Corregido aquí para evitar el SyntaxError
import requests
import streamlit as st
import pytz  # Librería para controlar zonas horarias de forma estricta

# Configuración de la plataforma
st.set_page_config(page_title="Monitoreo de actividad sismica", layout="wide")

# Endpoints globales de la USGS
USGS_ALL_HOUR = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
)
USGS_ALL_DAY = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
)

# Encabezados para evitar bloqueos de la API
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SeismoMonitor/3.0"}

@st.cache_data(ttl=60)
def obtener_estaciones_vivas_usgs():
    estaciones = {}
    try:
        response = requests.get(USGS_ALL_HOUR, headers=HEADERS, timeout=5)
        if response.status_code == 200:
            data = response.json()
            for feature in data.get("features", []):
                props = feature.get("properties", {})
                geom = feature.get("geometry", {})
                coords = geom.get("coordinates", [])
                lugar = props.get("place")
                if lugar and coords and props.get("mag") is not None:
                    estaciones[lugar] = [coords[1], coords[0], props.get("mag")]
    except Exception:
        pass

    if not estaciones:
        estaciones = {
            "CDMX (México)": [19.4326, -99.1332, 0.0],
            "California (EE.UU.)": [34.0, -118.2, 0.1],
            "Alaska (EE.UU.)": [61.2, -149.9, 0.2],
        }
    return estaciones

@st.cache_data(ttl=600)
def geocodificar_lugar_libre(nombre_lugar):
    try:
        url = f"https://nominatim.openstreetmap.org/search?q={nombre_lugar}&format=json&limit=1"
        response = requests.get(url, headers=HEADERS, timeout=5)
        if response.status_code == 200 and len(response.json()) > 0:
            data = response.json()[0]
            return [float(data["lat"]), float(data["lon"])]
    except Exception:
        pass
    return None

def haversine_distance(lat1, lon1, lat2, lon2):
    r = 6371
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    delta_phi = np.radians(lat2 - lat1)
    delta_lambda = np.radians(lon2 - lon1)
    a = (np.sin(delta_phi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(delta_lambda / 2) ** 2)
    return 2 * r * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

def obtener_actividad_region_real(lat_ref, lon_ref, radio_km=400):
    try:
        response = requests.get(USGS_ALL_HOUR, headers=HEADERS, timeout=5)
        if response.status_code == 200:
            data = response.json()
            sismos_locales = []
            for feature in data.get("features", []):
                props = feature.get("properties", {})
                geom = feature.get("geometry", {})
                coords = geom.get("coordinates", [])
                if coords and props.get("mag") is not None:
                    s_lon, s_lat = coords[0], coords[1]
                    distancia = haversine_distance(lat_ref, lon_ref, s_lat, s_lon)
                    if distancia <= radio_km:
                        sismos_locales.append({
                            "mag": props.get("mag"),
                            "place": props.get("place", "Sensor Local"),
                            "lat": s_lat,
                            "lon": s_lon,
                            "time": props.get("time") / 1000.0,
                        })
            if sismos_locales:
                return sorted(sismos_locales, key=lambda x: x["time"], reverse=True)[0]
    except Exception:
        pass
    return None

def obtener_todos_los_sismos_recientes(zona_horaria):
    lats, lons, mags, lugares, tiempos = [], [], [], [], []
    try:
        response = requests.get(USGS_ALL_DAY, headers=HEADERS, timeout=5)
        if response.status_code == 200:
            data = response.json()
            for feature in data.get("features", [])[:100]:
                props = feature.get("properties", {})
                geom = feature.get("geometry", {})
                coords = geom.get("coordinates", [])
                if coords and props.get("mag") is not None:
                    lats.append(coords[1])
                    lons.append(coords[0])
                    mags.append(props.get("mag"))
                    lugares.append(props.get("place", "Desconocido"))
                    epoch = props.get("time") / 1000.0
                    
                    # Convertir la hora del sismo global a la zona horaria seleccionada por el usuario
                    dt_utc = datetime.fromtimestamp(epoch, tz=pytz.utc)
                    dt_local = dt_utc.astimezone(zona_horaria)
                    tiempos.append(dt_local.strftime("%H:%M:%S"))
    except Exception:
        pass
    return pd.DataFrame({"lat": lats, "lon": lons, "Magnitud": mags, "Ubicación": lugares, "Hora": tiempos})

# CSS UI Profesional
st.markdown(
    """
    <style>
    .main {background-color: #050505;}
    .stMetric {background-color: #111; padding: 10px; border-radius: 4px; border: 1px solid #222;}
    .alert-box {
        padding: 15px; background: linear-gradient(90deg, #ff4b4b 0%, #8b0000 100%); 
        color: white; font-weight: bold; font-family: monospace;
        border-radius: 5px; text-align: center; margin-bottom: 10px; 
        border: 2px solid #ffffff; box-shadow: 0 0 15px rgba(255, 75, 75, 0.5);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Inicialización de Estados Globales
if "data" not in st.session_state:
    st.session_state.data = np.zeros(250)
    st.session_state.flags = np.zeros(250)
    st.session_state.logs = pd.DataFrame(columns=["Hora", "Magnitud", "Origen / Detalle", "Lugar", "Duración"])
    st.session_state.ultimo_check_api = 0
    st.session_state.mag_monitoreada = 0.0
    st.session_state.lugar_monitoreado = "Sin Actividad Extraordinaria"
    st.session_state.tiempo_sismo_activo = 0.0
    st.session_state.alerta_previa_activa = False
    st.session_state.id_sismo_actual = None

st.markdown("<h1 style='color: #00ff41; font-family: monospace; text-align: center;'>MONITOREO DE ACTIVIDAD SÍSMICA</h1>", unsafe_allow_html=True)

# Marcadores dinámicos principales
metrics_ph = st.empty()

col_graph, col_ctrl = st.columns([3, 1])

with col_ctrl:
    st.markdown("### ⚙️ Enlace de Telemetría")
    modo_seleccion = st.radio("Método de Ubicación", ["Búsqueda Libre Global 🔍", "Focos Activos en la última hora 📡"])
    
    region_actual_label = ""
    coords_base = [19.4326, -99.1332]
    mag_base_sugerida = 0.0
    
    if modo_seleccion == "Búsqueda Libre Global 🔍":
        entrada_usuario = st.text_input("Escribe cualquier país, estado o ciudad:", value="Oaxaca, Mexico")
        coords_buscadas = geocodificar_lugar_libre(entrada_usuario)
        if coords_buscadas:
            coords_base = coords_buscadas
            region_actual_label = entrada_usuario
        else:
            region_actual_label = "Sensor Resp. CDMX"
    else:
        diccionario_estaciones = obtener_estaciones_vivas_usgs()
        lista_viva_nombres = list(diccionario_estaciones.keys())
        region_seleccionada = st.selectbox("Seleccionar de la Red Activa:", lista_viva_nombres, index=0)
        coords_base = [diccionario_estaciones[region_seleccionada][0], diccionario_estaciones[region_seleccionada][1]]
        region_actual_label = region_seleccionada
        mag_base_sugerida = diccionario_estaciones[region_seleccionada][2]

    # Umbral por defecto en 5.0
    umbral = st.slider("Umbral de Alerta (Mag)", min_value=0.1, max_value=10.0, value=5.0, step=0.1)

    # Selector dinámico de Zona Horaria para los usuarios de la App
    opciones_tz = {
        "México (Centro) 🇲🇽": "America/Mexico_City",
        "Colombia 🇨🇴": "America/Bogota",
        "Perú 🇵🇪": "America/Lima",
        "Chile 🇨🇱": "America/Santiago",
        "Argentina 🇦🇷": "America/Buenos_Aires",
        "España (Madrid) 🇪🇸": "Europe/Madrid",
        "EE.UU. (Este - NY) 🇺🇸": "America/New_York",
        "EE.UU. (Pacífico - LA) 🇺🇸": "America/Los_Angeles",
        "Tiempo Universal (UTC) 🌐": "UTC"
    }
    tz_seleccionada_nombre = st.selectbox("Ajustar Zona Horaria Local 🕒", list(opciones_tz.keys()), index=0)
    ZONA_HORARIA_USER = pytz.timezone(opciones_tz[tz_seleccionada_nombre])

    st.markdown("**Área de Cobertura (400km):**")
    map_df = pd.DataFrame([coords_base], columns=["lat", "lon"])
    st.map(map_df, zoom=5)

with col_graph:
    alert_ph = st.empty()
    graph_ph = st.empty()

    st.markdown("### 📋 Registro de Alertas Locales")
    table_ph = st.empty()

    st.markdown("### 🌍 Mapa de Actividad Sísmica Global Reciente")
    map_global_ph = st.empty()

    st.markdown("### 🛑 Últimos Lugares del Mundo con Actividad")
    lugares_sismicos_ph = st.empty()

# Bucle Principal de Telemetría Sólido
while True:
    try:
        # Obtener tiempo exacto forzado a la zona horaria que el usuario seleccionó
        ahora_local = datetime.now(ZONA_HORARIA_USER)
        segundo = ahora_local.second + ahora_local.microsecond / 1e6
        tiempo_ahora = time.time()

        # Consulta controlada de la API cada 10 segundos para no saturar
        if st.session_state.ultimo_check_api == 0 or (tiempo_ahora - st.session_state.ultimo_check_api) > 10:
            st.session_state.ultimo_check_api = tiempo_ahora

            sismo_local = obtener_actividad_region_real(coords_base[0], coords_base[1])
            if sismo_local:
                st.session_state.mag_monitoreada = sismo_local["mag"]
                st.session_state.lugar_monitoreado = sismo_local["place"]
            else:
                if modo_seleccion == "Búsqueda Libre Global 🔍":
                    st.session_state.mag_monitoreada = round(np.random.uniform(0.05, 0.25), 2)
                    st.session_state.lugar_monitoreado = "Ruido Instrumental Base"
                else:
                    st.session_state.mag_monitoreada = mag_base_sugerida
                    st.session_state.lugar_monitoreado = f"Monitoreo Base: {region_actual_label}"
                    if st.session_state.mag_monitoreada == 0.0:
                        st.session_state.mag_monitoreada = round(np.random.uniform(0.05, 0.25), 2)
                        st.session_state.lugar_monitoreado = "Ruido Instrumental Estación"

            df_global = obtener_todos_los_sismos_recientes(ZONA_HORARIA_USER)
            
            # Pintar mapa global de forma estable
            if not df_global.empty:
                fig_mapa = go.Figure(go.Scattermapbox(
                    lat=df_global["lat"], lon=df_global["lon"], mode="markers",
                    marker=go.scattermapbox.Marker(size=df_global["Magnitud"] * 3.5 + 2, color=df_global["Magnitud"], colorscale="YlOrRd", showscale=True, cmin=0, cmax=6),
                    text=df_global["Ubicación"] + " | M: " + df_global["Magnitud"].astype(str), hoverinfo="text"
                ))
                fig_mapa.update_layout(mapbox=dict(style="carto-darkmatter", zoom=1, center=dict(lat=20, lon=-20)), margin=dict(l=0, r=0, t=5, b=5), paper_bgcolor="#050505", plot_bgcolor="#050505", height=250, showlegend=False)
                map_global_ph.plotly_chart(fig_mapa, use_container_width=True, config={"displayModeBar": False})

                html_lugares = ""
                for _, fila in df_global.head(5).iterrows():
                    m = fila["Magnitud"]
                    clase_css = "background-color:#4a0e0e;border-left:5px solid #ff4b4b;color:#ff9999;" if m >= 4.5 else ("background-color:#4a330e;border-left:5px solid #ffaa00;color:#ffe0b3;" if m >= 2.5 else "background-color:#112211;border-left:5px solid #00ff41;color:#b3ffb3;")
                    html_lugares += f"""
                    <div style='padding:8px 12px;margin-bottom:6px;border-radius:4px;font-family:monospace;font-size:13px;display:flex;justify-content:space-between;{clase_css}'>
                        <span>📍 {fila['Ubicación']}</span>
                        <span><b>M {m:.1f}</b> ({fila['Hora']})</span>
                    </div>
                    """
                lugares_sismicos_ph.markdown(html_lugares, unsafe_allow_html=True)

        # Lógica de Umbrales y Simulación de Ondas Sísmicas
        es_alerta_activa = st.session_state.mag_monitoreada >= umbral

        if es_alerta_activa:
            st.session_state.tiempo_sismo_activo += 0.08
            nuevo_val = (np.sin(segundo * 16) * st.session_state.mag_monitoreada) + np.random.normal(0, 0.2)
            alert_ph.markdown(f"<div class='alert-box'>🚨 ALERTA DE SISMO EN {region_actual_label.upper()}: REGISTRO DE M {st.session_state.mag_monitoreada:.1f} | TIEMPO TRANSCURRIDO: {st.session_state.tiempo_sismo_activo:.1f}s</div>", unsafe_allow_html=True)
        else:
            if st.session_state.alerta_previa_activa and st.session_state.id_sismo_actual in st.session_state.logs.index:
                st.session_state.logs.at[st.session_state.id_sismo_actual, "Duración"] = f"{st.session_state.tiempo_sismo_activo:.1f} s"
            st.session_state.tiempo_sismo_activo = 0.0
            nuevo_val = (np.sin(segundo * 4) * st.session_state.mag_monitoreada) + np.random.normal(0, 0.05)
            alert_ph.empty()

        st.session_state.data = np.append(st.session_state.data[1:], nuevo_val)
        st.session_state.flags = np.append(st.session_state.flags[1:], 1 if es_alerta_activa else 0)

        # Renderizado de los Recuadros de Métricas Superiores
        with metrics_ph.container():
            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("ESTADO SENSOR", "CRÍTICO" if es_alerta_activa else "NORMAL")
            m2.metric("MAGNITUD EN ZONA", f"{st.session_state.mag_monitoreada:.2f}")
            m3.metric("LÍMITE UMBRAL", f"{umbral:.1f}")
            m4.metric("ALERTAS REGISTRADAS", len(st.session_state.logs))
            m5.metric("LUGAR MONITOREADO", f"📡 {region_actual_label[:14]}...")
            m6.metric("HORA AJUSTADA", ahora_local.strftime("%H:%M:%S"))

        # Dibujar Gráfica Dinámica Fluida
        fig = go.Figure()
        fig.add_trace(go.Scatter(y=st.session_state.data, mode="lines", line=dict(color="#00ff41", width=1.5)))
        y_rojo = [v if f == 1 else None for v, f in zip(st.session_state.data, st.session_state.flags)]
        fig.add_trace(go.Scatter(y=y_rojo, mode="lines", line=dict(color="#ff4b4b", width=2.5)))
        fig.update_layout(template="plotly_dark", height=260, margin=dict(l=40, r=20, t=10, b=10), plot_bgcolor="#050505", paper_bgcolor="#050505", yaxis=dict(range=[-11, 11]), xaxis=dict(showgrid=False), showlegend=False)
        graph_ph.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        # Control del Historial de Registros Local
        if es_alerta_activa and not st.session_state.alerta_previa_activa:
            nuevo_log = pd.DataFrame({
                "Hora": [ahora_local.strftime("%H:%M:%S")],
                "Magnitud": [f"M {st.session_state.mag_monitoreada:.1f}"],
                "Origen / Detalle": [st.session_state.lugar_monitoreado],
                "Lugar": [region_actual_label[:20]],
                "Duración": ["En curso..."]
            })
            st.session_state.logs = pd.concat([nuevo_log, st.session_state.logs]).reset_index(drop=True).head(10)
            st.session_state.id_sismo_actual = 0

        if es_alerta_activa and st.session_state.id_sismo_actual in st.session_state.logs.index:
            st.session_state.logs.at[st.session_state.id_sismo_actual, "Duración"] = f"{st.session_state.tiempo_sismo_activo:.1f} s (Activo)"

        st.session_state.alerta_previa_activa = es_alerta_activa
        table_ph.dataframe(st.session_state.logs, use_container_width=True)

    except Exception:
        pass
    time.sleep(0.08)
