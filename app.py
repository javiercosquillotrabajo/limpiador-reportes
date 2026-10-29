import io
import re
import fitz  # PyMuPDF
from PIL import Image
import streamlit as st

st.set_page_config(page_title="Anonimizador de Reportes", page_icon="🔒", layout="centered")

st.title("🔒 Limpiador de Reportes (Equifax / Experian)")
st.write("Pixela **Apellidos**, **DNI/RUC** y **Datos del Usuario**, manteniendo legibles los **nombres de pila** y las **fechas**.")

ETIQUETAS_USUARIO = [
    "Usuario:", "Solicitado por:", "Consultado por:", "Cliente:", 
    "Razón Social Solicitante:", "Generado por:", "Entidad Solicitante:"
]

def es_fecha_o_hora(texto):
    """Detecta si un texto contiene formato de fecha o separadores de hora"""
    if "/" in texto or ":" in texto:
        return True
    # Si es una fecha DDMMAAAA sin separadores (ej. 26102026)
    palabra = re.sub(r'[^\w]', '', texto)
    if re.match(r'^(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])(19|20)\d{2}$', palabra):
        return True
    return False

def censurar_pdf(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    apellidos_detectados = set()
    
    for page in doc:
        rects_a_pixelar = []
        words = page.get_text("words")  # (x0, y0, x1, y1, "texto", block_no, line_no, word_no)
        
        # 1. Agrupar palabras por línea para aislar apellidos de nombres
        lineas = {}
        for w in words:
            y_center = round((w[1] + w[3]) / 2, 0)
            encontrado = False
            for y_key in lineas:
                if abs(y_key - y_center) <= 5:
                    lineas[y_key].append(w)
                    encontrado = True
                    break
            if not encontrado:
                lineas[y_center] = [w]

        # 2. Detectar nombres en la barra: "DNI XXXXXXXX - APELLIDOS NOMBRES"
        for y_key, line_words in lineas.items():
            line_words.sort(key=lambda x: x[0])
            textos = [w[4] for w in line_words]
            
            tiene_guion = any("-" in t or "–" in t for t in textos)
            tiene_dni = any(t.upper() in ["DNI", "RUC", "CE"] for t in textos)
            
            if tiene_guion or tiene_dni:
                idx_inicio = -1
                for i, w in enumerate(line_words):
                    if "-" in w[4] or "–" in w[4]:
                        idx_inicio = i + 1
                        break
                    num_limpio = re.sub(r'[^\w]', '', w[4])
                    if num_limpio.isdigit() and len(num_limpio) >= 8:
                        idx_inicio = i + 1
                
                if idx_inicio != -1 and idx_inicio < len(line_words):
                    palabras_nombre = [
                        w for w in line_words[idx_inicio:] 
                        if re.sub(r'[^A-ZÁÉÍÓÚÑa-z]', '', w[4]).isalpha() and len(w[4]) > 1
                    ]
                    
                    # Ocultar los 2 primeros términos (Apellidos) y dejar los nombres
                    if len(palabras_nombre) >= 3:
                        for ap in palabras_nombre[:2]:
                            rects_a_pixelar.append(fitz.Rect(ap[0], ap[1], ap[2], ap[3]))
                            apellidos_detectados.add(re.sub(r'[^A-ZÁÉÍÓÚÑa-z]', '', ap[4]).upper())
                    elif len(palabras_nombre) == 2:
                        ap = palabras_nombre[0]
                        rects_a_pixelar.append(fitz.Rect(ap[0], ap[1], ap[2], ap[3]))
                        apellidos_detectados.add(re.sub(r'[^A-ZÁÉÍÓÚÑa-z]', '', ap[4]).upper())

        # 3. Censurar DNI (8 dígitos), RUC (11 dígitos) y apellidos que se repitan
        for w in words:
            texto_raw = w[4]
            
            # Proteger fechas y horas estrictamente
            if es_fecha_o_hora(texto_raw):
                continue
                
            palabra_limpia = re.sub(r'[^A-ZÁÉÍÓÚÑa-z0-9]', '', texto_raw)
            
            # Pixelar número de DNI (8 dígitos) o RUC (11 dígitos)
            if (len(palabra_limpia) == 8 and palabra_limpia.isdigit()) or (len(palabra_limpia) == 11 and palabra_limpia.isdigit()):
                rects_a_pixelar.append(fitz.Rect(w[0], w[1], w[2], w[3]))
                continue
            
            # Pixelar apellidos detectados si vuelven a aparecer en el texto
            if palabra_limpia.upper() in apellidos_detectados:
                rects_a_pixelar.append(fitz.Rect(w[0], w[1], w[2], w[3]))

        # 4. Censurar bloque completo de Usuario (ID y Nombre del consultante)
        for etiqueta in ETIQUETAS_USUARIO:
            matches_user = page.search_for(etiqueta)
            for r_user in matches_user:
                # Buscar si la fecha de creación está en la misma fila para frenar antes de ella
                matches_fecha = page.search_for("Fecha")
                x1_tope = r_user.x0 + 320  # tope por defecto
                
                for r_fec in matches_fecha:
                    if abs(r_fec.y0 - r_user.y0) < 8 and r_fec.x0 > r_user.x1:
                        x1_tope = r_fec.x0 - 8
                        break
                
                rects_a_pixelar.append(fitz.Rect(r_user.x0, r_user.y0 - 2, x1_tope, r_user.y1 + 2))

        # 5. APLICAR EFECTO PIXELEADO / MOSAICO
        imagenes_pixeladas = []
        for rect in rects_a_pixelar:
            pix = page.get_pixmap(clip=rect, dpi=150)
            if pix.width < 4 or pix.height < 4:
                continue
            
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            w_small = max(2, int(pix.width / 9))
            h_small = max(2, int(pix.height / 7))
            img_small = img.resize((w_small, h_small), resample=Image.Resampling.BILINEAR)
            img_pix = img_small.resize((pix.width, pix.height), resample=Image.Resampling.NEAREST)
            
            img_bytes = io.BytesIO()
            img_pix.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            imagenes_pixeladas.append((rect, img_bytes.getvalue()))

        # Borrado del texto subyacente con máscara blanca
        for rect in rects_a_pixelar:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()

        # Insertar imagen pixelada sobre el espacio borrado
        for rect, img_data in imagenes_pixeladas:
            page.insert_image(rect, stream=img_data)

    output_stream = io.BytesIO()
    doc.save(output_stream, garbage=4, deflate=True)
    doc.close()
    output_stream.seek(0)
    return output_stream

uploaded_file = st.file_uploader("Arrastra o selecciona el reporte en PDF", type=["pdf"])

if uploaded_file is not None:
    st.info(f"Reporte cargado: **{uploaded_file.name}**")
    
    if st.button("🚀 Ocultar Datos Sensibles"):
        with st.spinner("Pixelando apellidos, DNI y datos de usuario..."):
            pdf_limpio = censurar_pdf(uploaded_file.read())
            st.success("¡Documento procesado con éxito!")
            
            st.download_button(
                label="📥 Descargar PDF Limpio",
                data=pdf_limpio,
                file_name=uploaded_file.name.replace(".pdf", "_anonimizado.pdf"),
                mime="application/pdf"
            )
