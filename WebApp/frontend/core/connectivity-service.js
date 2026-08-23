// connectivity-service.js
import { db } from "./firebase-init.js";

class ConnectivityService {
    constructor() {
        this.status = navigator.onLine ? 'online' : 'offline';
        this.listeners = [];
        this.pingUrl = './favicon.ico'; // Usiamo la favicon locale per il ping
        this.pingInterval = 10000; // 10 secondi per rilevamento reattivo
        this.pingTimeout = 4000;   // 4 secondi timeout
        this.intervalId = null;
        this.consecutiveFailures = 0;

        this.init();
    }

    init() {
        window.addEventListener('online', () => this.handleNetworkChange(true));
        window.addEventListener('offline', () => this.handleNetworkChange(false));

        // Avvia il ping periodico se inizialmente online
        if (navigator.onLine) {
            this.startPingInterval();
        }
    }

    addEventListener(callback) {
        this.listeners.push(callback);
        // Notifica immediatamente dello stato attuale
        callback(this.status);
    }

    removeEventListener(callback) {
        this.listeners = this.listeners.filter(l => l !== callback);
    }

    async handleNetworkChange(isOnline) {
        if (!isOnline) {
            this.consecutiveFailures = 0;
            this.updateStatus('offline');
            this.stopPingInterval();
        } else {
            const actualOnline = await this.ping();
            if (actualOnline) {
                this.consecutiveFailures = 0;
                this.updateStatus('online');
            } else {
                this.consecutiveFailures = 1;
                this.updateStatus('unstable');
            }
            this.startPingInterval();
        }
    }

    updateStatus(newStatus) {
        if (this.status !== newStatus) {
            console.log(`[ConnectivityService] Stato connessione cambiato in: ${newStatus.toUpperCase()}`);
            this.status = newStatus;
            this.notifyListeners();
        }
    }

    notifyListeners() {
        this.listeners.forEach(callback => {
            try {
                callback(this.status);
            } catch (e) {
                console.error("[ConnectivityService] Errore notifica listener:", e);
            }
        });
    }

    startPingInterval() {
        this.stopPingInterval();
        this.intervalId = setInterval(async () => {
            if (navigator.onLine) {
                const isOnline = await this.ping();
                if (isOnline) {
                    this.consecutiveFailures = 0;
                    this.updateStatus('online');
                } else {
                    this.consecutiveFailures++;
                    if (this.consecutiveFailures >= 3) {
                        this.updateStatus('offline');
                    } else {
                        this.updateStatus('unstable');
                    }
                }
            } else {
                this.consecutiveFailures = 0;
                this.updateStatus('offline');
            }
        }, this.pingInterval);
    }

    stopPingInterval() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
    }

    async ping() {
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), this.pingTimeout);

            const response = await fetch(`${this.pingUrl}?t=${Date.now()}`, {
                method: 'HEAD',
                signal: controller.signal,
                cache: 'no-store'
            });

            clearTimeout(timeoutId);
            return response.ok;
        } catch (e) {
            console.warn("[ConnectivityService] Ping fallito (nessuna rotta internet o instabile):", e.message);
            return false;
        }
    }

    getStatus() {
        return this.status;
    }
}

export const connectivityService = new ConnectivityService();
