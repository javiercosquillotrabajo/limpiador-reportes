import io
import re
import fitz  # PyMuPDF
from PIL import Image
import streamlit as st

st.set_page_config(page_title="Anonimizador de Reportes", page_icon="🔒", layout="centered")

st.title("🔒 Limpiador de Reportes (Equifax / Experian)")
st.write("Oculta **apellidos**, DNI, RUC y usuario consultante con **efecto pixelado**, manteniendo nombres y fechas visibles.")

ETIQUETAS_USUARIO = [
    "Usuario:", "Solicitado por:", "Consultado por:", "Cliente:", 
    "Razón Social Solicitante:", "Generado por:", "Entidad Solicitante:"
]

PATRON_DNI = re.compile(r'^\d{8}$')
PATRON_RUC = re.compile(r'^(10|20|15|17)\d{9}$')

def es_fecha(texto):
    """Detecta si una palabra contiene formato de fecha o separadores"""
    return "/" in texto or "-" in texto or ":" in texto or "." in texto

def extraer_apellidos(doc):
    """Identifica con precisión los apellidos del titular usando bloques de texto válidos"""
    apellidos = set()
    nombres_a_salvar = set()
    
    etiquetas_nombre = [
        "apellidos y nombres", "nombre / razón social", "nombre/razón social", 
        "razón social / nombre", "sujeto evaluado", "titular", "persona evaluada"
    ]
    
    for page in doc:
        # Usamos 'blocks', que es 100% compatible con todas las versiones de PyMuPDF
        blocks = page.get_text("blocks")
        for b in blocks:
            if b[6] != 0:  # Ignorar bloques que no sean de texto
                continue
            texto_bloque = b[4]
            lineas = [l.strip() for l in texto_bloque.splitlines() if l.strip()]
            
            for idx, l in enumerate(lineas):
                l_lower = l.lower()
                
                # Caso A: Si existen campos específicos de apellidos
                if "apellido paterno" in l_lower:
                    val = re.sub(r'(?i)apellido\s+paterno[\s:]*', '', l).strip()
                    if not val and idx + 1 < len(lineas):
                        val = lineas[idx+1].strip()
                    for w in re.findall(r'[A-ZÁÉÍÓÚÑa-záéíóúñ]+', val):
                        if len(w) > 2:
                            apellidos.add(w.upper())
                
                if "apellido materno" in l_lower:
                    val = re.sub(r'(?i)apellido\s+materno[\s:]*', '', l).strip()
                    if not val and idx + 1 < len(lineas):
                        val = lineas[idx+1].strip()
                    for w in re.findall(r'[A-ZÁÉÍÓÚÑa-záéíóúñ]+', val):
                        if len(w) > 2:
                            apellidos.add(w.upper())

                if "nombres" in l_lower and "apellidos" not in l_lower:
                    val = re.sub(r'(?i)nombres?[\s:]*', '', l).strip()
                    if not val and idx + 1 < len(lineas):
                        val = lineas[idx+1].strip()
                    for w in re.findall(r'[A-ZÁÉÍÓÚÑa-záéíóúñ]+', val):
                        if len(w) > 2:
                            nombres_a_salvar.add(w.upper())

                # Caso B: Formato con coma (ej. GONZALES CARDENAS, ANTHONY PAOLO)
                if "," in l and not any(c in l for c in ["/", "$", "S/.", "%"]):
                    partes_coma = l.split(",")
                    if len(partes_coma) == 2:
                        antes = [w.upper() for w in re.findall(r'[A-ZÁÉÍÓÚÑa-záéíóúñ]+', partes_coma[0]) if len(w) > 2]
                        despues = [w.upper() for w in re.findall(r'[A-ZÁÉÍÓÚÑa-záéíóúñ]+', partes_coma[1]) if len(w) > 2]
                        if 1 <= len(antes) <= 3 and 1 <= len(despues) <= 3:
                            for a in antes:
                                apellidos.add(a)
                            for d in despues:
                                nombres_a_salvar.add(d)

                # Caso C: Etiquetas combinadas (Apellidos y Nombres / Nombre / Razón Social)
                for etiq in etiquetas_nombre:
                    if etiq in l_lower:
                        val = re.sub(rf'(?i){etiq}[\s:]*', '', l).strip()
                        if not val and idx + 1 < len(lineas):
                            val = lineas[idx+1].strip()
                        
                        palabras = [w.upper() for w in re.findall(r'[A-ZÁÉÍÓÚÑa-záéíóúñ]+', val) if len(w) > 2]
                        palabras = [p for p in palabras if p not in ["DEL", "DE", "LA", "LOS", "SAN", "SANTA"]]
                        
                        if len(palabras) >= 4:
                            # 2 apellidos + 2 nombres
                            apellidos.add(palabras[0])
                            apellidos.add(palabras[1])
                            for n in palabras[2:]:
                                nombres_a_salvar.add(n)
                        elif len(palabras) == 3:
                            # 2 apellidos + 1 nombre
                            apellidos.add(palabras[0])
                            apellidos.add(palabras[1])
                            nombres_a_salvar.add(palabras[2])
                        elif len(palabras) == 2:
                            apellidos.add(palabras[0])
                            nombres_a_salvar.add(palabras[1])

    # Asegurar que ningún nombre de pila quede en la lista de apellidos
    for n in nombres_a_salvar:
        if n in apellidos:
            apellidos.remove(n)

    return apellidos

def censurar_pdf(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    # Extraer los apellidos a pixelar
    apellidos_a_pixelar = extraer_apellidos(doc)
    
    for page in doc:
        rects_a_pixelar = []
        words = page.get_text("words")  # (x0, y0, x1, y1, "texto", block_no, line_no, word_no)
        
        for w in words:
            texto_raw = w[4]
            palabra_limpia = re.sub(r'[^A-ZÁÉÍÓÚÑa-z0-9]', '', texto_raw)
            
            # 1. Pixelar SOLO APELLIDOS
            if palabra_limpia.upper() in apellidos_a_pixelar:
                rects_a_pixelar.append(fitz.Rect(w[0], w[1], w[2], w[3]))
                continue
            
            # Si contiene fecha o separadores, NO se toca
            if es_fecha(texto_raw):
                continue
            
            # 2. Pixelar DNI y RUC
            if PATRON_DNI.match(palabra_limpia) or PATRON_RUC.match(palabra_limpia):
                rects_a_pixelar.append(fitz.Rect(w[0], w[1], w[2], w[3]))

        # 3. Pixelar usuario consultante (ancho seguro)
        for etiqueta in ETIQUETAS_USUARIO:
            matches = page.search_for(etiqueta)
            for rect in matches:
                rects_a_pixelar.append(fitz.Rect(rect.x0, rect.y0 - 1, rect.x1 + 130, rect.y1 + 1))

        # 4. APLICAR EFECTO PIXELEADO / MOSAICO
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

        # Borrado del texto subyacente con máscara blanca limpia
        for rect in rects_a_pixelar:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()

        # Insertar imagen pixelada sobre el espacio
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
        with st.spinner("Pixelando apellidos, DNI y usuario..."):
            pdf_limpio = censurar_pdf(uploaded_file.read())
            st.success("¡Documento procesado con éxito!")
            
            st.download_button(
                label="📥 Descargar PDF Limpio",
                data=pdf_limpio,
                file_name=uploaded_file.name.replace(".pdf", "_anonimizado.pdf"),
                mime="application/pdf"
            )
