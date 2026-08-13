import { db, app } from "./core/firebase-init.js";
import { getStorage, ref, uploadBytes } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-storage.js";
import { getFunctions, httpsCallable } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-functions.js";

const storage = getStorage(app);
const functions = getFunctions(app, "europe-west1");
document.addEventListener('DOMContentLoaded', () => {
    // Hide AI by default, wait for auth sync to show it if admin
    const aiTab = document.getElementById('tab-ai-chat');
    if (aiTab) aiTab.style.display = 'none';
    
    document.getElementById('fileAI').addEventListener('change', async (e) => {
        if(e.target.files.length) {
            const file = e.target.files[0];
            await processaFileAI(file);
        }
    });
    
    // Auth observer per abilitare UI solo agli amministratori
    import('https://www.gstatic.com/firebasejs/10.8.0/firebase-auth.js').then(authModule => {
        import('https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js').then(firestoreModule => {
            const auth = authModule.getAuth(app);
            const firestoreDb = firestoreModule.getFirestore(app);
            authModule.onAuthStateChanged(auth, async (user) => {
                if (user) {
                    const docSnap = await firestoreModule.getDoc(firestoreModule.doc(firestoreDb, "dipendenti", user.uid));
                    if (docSnap.exists() && docSnap.data().ruolo === 'amministratore') {
                        if (aiTab) aiTab.style.display = 'block';
                    }
                }
            });
        });
    });
});

let isAIProcessing = false;
async function processaFileAI(file) {
    if (isAIProcessing) return;
    isAIProcessing = true;
    document.getElementById('loadingOverlay').style.display = 'flex';
    document.getElementById('loadingText').innerText = "Caricamento documento nel cloud...";
    try {
        const timestamp = new Date().getTime();
        const filePath = `imports/documenti_ai/${timestamp}_${file.name}`;
        await uploadBytes(ref(storage, filePath), file);

        document.getElementById('loadingText').innerText = "L'Intelligenza Artificiale sta leggendo il documento... (potrebbe richiedere un po' di tempo)";
        
        const agentExtractor = httpsCallable(functions, 'agent_extractor', { timeout: 120000 });
        const res = await agentExtractor({ filePath: filePath });
        
        if (res.data && res.data.status === 'success') {
            Swal.fire("Successo", res.data.message || "Dati estratti e salvati correttamente!", "success");
        } else {
            throw new Error(res.data ? res.data.message : "Errore sconosciuto dall'Agente");
        }
    } catch(e) {
        console.error("ERRORE AGENTE AI:", e);
        Swal.fire("Errore Server", e.message || "Impossibile completare l'estrazione.", "error");
    } finally {
        document.getElementById('fileAI').value = '';
        document.getElementById('loadingOverlay').style.display = 'none';
        isAIProcessing = false;
    }
}

window.speakText = function(text) {
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const msg = new SpeechSynthesisUtterance(text);
        msg.lang = 'it-IT';
        msg.rate = 1.0;
        
        const voices = window.speechSynthesis.getVoices();
        const italianVoices = voices.filter(v => v.lang.startsWith('it'));
        let femaleVoice = italianVoices.find(v => 
            v.name.includes('Elsa') || 
            v.name.includes('Alice') || 
            v.name.includes('Google') || 
            v.name.includes('Bianca')
        );
        
        if (femaleVoice) {
            msg.voice = femaleVoice;
        } else if (italianVoices.length > 0) {
            msg.voice = italianVoices[0];
        }

        window.speechSynthesis.speak(msg);
    }
};

let isChatProcessing = false;
window.sendChatMessage = async function() {
    if (isChatProcessing) return;
    const input = document.getElementById('chatInputText');
    const text = input.value.trim();
    if (!text) return;
    if (text.length > 1000) {
        Swal.fire("Attenzione", "Messaggio troppo lungo (max 1000 caratteri)", "warning");
        return;
    }
    
    isChatProcessing = true;
    input.disabled = true;
    
    const messagesDiv = document.getElementById('chatMessages');
    
    const userMsg = document.createElement('div');
    userMsg.className = 'chat-message user';
    userMsg.innerText = text;
    messagesDiv.appendChild(userMsg);
    
    input.value = '';
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    
    const loadingMsg = document.createElement('div');
    loadingMsg.className = 'chat-message ai';
    loadingMsg.innerHTML = '<span style="color:#64748b;">Sto elaborando la tua richiesta...</span>';
    messagesDiv.appendChild(loadingMsg);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    try {
        const meseSelezionato = '2026-07'; 
        
        const chatAgent = httpsCallable(functions, 'agent_chat_assistant');
        const response = await chatAgent({ message: text, mese: meseSelezionato });
        
        if (messagesDiv.contains(loadingMsg)) {
            messagesDiv.removeChild(loadingMsg);
        }
        
        if (response.data && response.data.status === 'success') {
            const replyText = response.data.reply;
            const aiMsg = document.createElement('div');
            aiMsg.className = 'chat-message ai';
            aiMsg.innerHTML = `<strong>Assistente Logistico AI</strong><br>${replyText.replace(/\\n/g, '<br>')}`;
            messagesDiv.appendChild(aiMsg);
            
            window.speakText(replyText);
        } else {
            throw new Error(response.data ? response.data.message : "Errore AI");
        }
    } catch(e) {
        if (messagesDiv.contains(loadingMsg)) {
            messagesDiv.removeChild(loadingMsg);
        }
        const errorMsg = document.createElement('div');
        errorMsg.className = 'chat-message ai';
        errorMsg.innerHTML = `<strong style="color:red">Errore Server:</strong> ${e.message}`;
        messagesDiv.appendChild(errorMsg);
    } finally {
        isChatProcessing = false;
        input.disabled = false;
        input.focus();
    }
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
};

window.startDictation = function() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = "it-IT";
        
        const micBtn = document.getElementById('micButton');
        const oldBg = micBtn.style.background;
        const oldColor = micBtn.style.color;
        micBtn.style.background = '#dc2626'; 
        micBtn.style.color = '#ffffff';
        
        recognition.start();
        
        recognition.onresult = function(e) {
            const inputField = document.getElementById('chatInputText');
            const currentVal = inputField.value;
            inputField.value = currentVal + (currentVal ? " " : "") + e.results[0][0].transcript;
            micBtn.style.background = oldBg;
            micBtn.style.color = oldColor;
            recognition.stop();
        };
        
        recognition.onerror = function(e) {
            console.error("Speech recognition error", e);
            micBtn.style.background = oldBg;
            micBtn.style.color = oldColor;
            recognition.stop();
        };
        
        recognition.onend = function() {
            micBtn.style.background = oldBg;
            micBtn.style.color = oldColor;
        };
    } else {
        if(typeof Swal !== 'undefined') {
            Swal.fire("Non Supportato", "Il tuo browser non supporta la dettatura vocale nativa. Usa Google Chrome o Microsoft Edge.", "warning");
        } else {
            alert("Il tuo browser non supporta la dettatura vocale.");
        }
    }
};
