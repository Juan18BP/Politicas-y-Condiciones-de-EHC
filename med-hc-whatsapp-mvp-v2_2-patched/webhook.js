const express = require("express");
const axios = require("axios");
require("dotenv").config();

const app = express();
app.use(express.json());

const PHONE_NUMBER_ID = process.env.PHONE_NUMBER_ID;
const TOKEN = process.env.TOKEN;
const VERIFY_TOKEN = process.env.VERIFY_TOKEN || "mi_token_secreto";

// Verificación inicial del webhook
app.get("/webhook", (req, res) => {
  const mode = req.query["hub.mode"];
  const token = req.query["hub.verify_token"];
  const challenge = req.query["hub.challenge"];

  if (mode && token && mode === "subscribe" && token === VERIFY_TOKEN) {
    res.status(200).send(challenge);
  } else {
    res.sendStatus(403);
  }
});

// Recepción de mensajes y botones
app.post("/webhook", async (req, res) => {
  const body = req.body;

  if (body.object === "whatsapp_business_account") {
    body.entry.forEach(entry => {
      entry.changes.forEach(change => {
        const messages = change.value.messages || [];
        messages.forEach(async msg => {
          if (msg.type === "button") {
            const respuesta = msg.button.text;
            const from = msg.from;

            console.log(`Respuesta del paciente (${from}): ${respuesta}`);

            if (respuesta === "Aceptar") {
              console.log("Paciente aceptó ✅. Enviar PDF...");

              try {
                await axios.post(
                  `https://graph.facebook.com/v20.0/${PHONE_NUMBER_ID}/messages`,
                  {
                    messaging_product: "whatsapp",
                    to: from,
                    type: "document",
                    document: {
                      link: "https://tuservidor.com/historia.pdf",
                      filename: "historia_clinica.pdf"
                    }
                  },
                  {
                    headers: {
                      Authorization: `Bearer ${TOKEN}`,
                      "Content-Type": "application/json"
                    }
                  }
                );
                console.log("PDF enviado correctamente ✅");
              } catch (error) {
                console.error("Error al enviar PDF:", error.response?.data || error.message);
              }
            } else if (respuesta === "Rechazar") {
              console.log("Paciente rechazó ❌. No se envía nada.");
            }
          }
        });
      });
    });
    res.sendStatus(200);
  } else {
    res.sendStatus(404);
  }
});

app.listen(3000, () => {
  console.log("Servidor webhook en http://localhost:3000/webhook");
});
