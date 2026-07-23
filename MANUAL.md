# Bot Manada — Manual de instalación (15 minutos)

Bot de Telegram que cada noche a las **10:00pm (hora Ciudad de México)** te hace
4 preguntas con botones Sí/No y lleva tus rachas:

- 💧 ¿Tomé al menos 2 litros de agua?
- 🙏 ¿Tuve una oración profunda con Jehová?
- 📖 ¿Leí al menos 10 minutos?
- 💪 ¿Hice al menos 30 minutos de ejercicio?

Comandos: `/start` (registrarte), `/hoy` (contestar ahora), `/resumen` (últimos 7 días + rachas).

---

## Paso 1 — Tu bot de Telegram (ya está hecho)

El bot ya existe: **@Lamanada_aullando_bot**. Su token te lo pasa Raúl.
Si algún día quieres regenerar el token: habla con **@BotFather** → `/mybots` →
tu bot → API Token → Revoke.

## Paso 2 — Base de datos gratis (Supabase, 5 min)

Sin esto el bot funciona, pero **pierde el historial cada vez que el servidor
se reinicia**. Con esto, tus datos quedan guardados para siempre.

1. Entra a https://supabase.com → **Start your project** → crea cuenta (con Google es 1 clic).
2. **New project** → nombre: `bot-manada` → contraseña la que sea → región la más cercana → Create.
3. Cuando cargue, ve al menú izquierdo → **SQL Editor** → pega esto y dale **Run**:

   ```sql
   create table bot_data (id int primary key, data jsonb);
   ```

4. Ve a **Settings → API** y copia dos cosas:
   - **Project URL** (algo como `https://abcdefgh.supabase.co`)
   - **secret key** (la que empieza con `sb_secret_...` o la "service_role")

## Paso 3 — Servidor en Render (donde vive el bot)

1. Entra a https://render.com → crea tu cuenta.
2. Botón **New +** → **Background Worker**.
3. Elige **Public Git Repository** y pega:
   `https://github.com/lobitoylobitarp-rgb/bot-manada`
4. Configuración:
   - Name: `bot-manada`
   - Language: Python 3
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
   - Plan: **Starter** (es el más barato para workers)
5. Antes de crear, en **Environment Variables** agrega estas 3:

   | Variable       | Valor                                    |
   |----------------|------------------------------------------|
   | `BOT_TOKEN`    | el token que te pasó Raúl                |
   | `SUPABASE_URL` | tu Project URL del paso 2                |
   | `SUPABASE_KEY` | tu secret key del paso 2                 |

6. **Create Background Worker** y espera a que diga "Live" (2-3 min).

## Paso 4 — Probar

1. En Telegram busca **@Lamanada_aullando_bot** y mándale `/start`.
2. Mándale `/hoy` → deben salir las 4 preguntas una por una con botones.
3. Contesta las 4 → debe decir "✅ Día guardado: X/4".
4. Mándale `/resumen` → debe mostrar tu cuadrícula de la semana.

Desde hoy, cada noche a las 10pm te llegan solas las 4 preguntas. Si un día no
contestas, ese día rompe la racha (así debe ser 😉).

---

## Problemas comunes

- **El bot no contesta**: en Render revisa la pestaña **Logs**. Si dice
  `Unauthorized`, el `BOT_TOKEN` está mal copiado.
- **"save bloqueado ... anti-wipe"** en logs: el bot no pudo leer Supabase al
  arrancar (URL o KEY mal). Revisa las variables y reinicia el servicio.
- **Se borró mi historial**: pusiste mal Supabase (paso 2) y estaba guardando
  local. Configura las variables y listo.
- **Cambiar la hora de las preguntas**: en `bot.py` busca `dt_time(22, 0` y
  cambia el 22 por la hora que quieras (formato 24h, hora CDMX).
