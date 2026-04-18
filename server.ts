import express from 'express';
import { WebSocketServer, WebSocket } from 'ws';
import { createServer } from 'http';
import dotenv from 'dotenv';

dotenv.config();

const app = express();
const port = 8765;
const server = createServer(app);
const wss = new WebSocketServer({ server });

console.log('AI Backend starting on port', port);

wss.on('connection', (ws: WebSocket) => {
    console.log('Client connected');

    ws.on('message', (data: Buffer | string) => {
        if (data instanceof Buffer) {
            // Echo back audio or just log receipt
            // console.log(`Received binary data: ${data.length} bytes`);
        } else {
            console.log('Received text:', data.toString());
        }
    });

    // Mock an initial welcome message
    setTimeout(() => {
        ws.send(JSON.stringify({
            type: 'llm',
            text: 'System online. Bemo Edition ready.',
            emotion: 'happy'
        }));
    }, 2000);

    // Mock periodically changing emotions for testing UI
    let i = 0;
    const emotions = ['neutral', 'happy', 'thinking', 'talking', 'sad'];
    const interval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
            const emotion = emotions[i % emotions.length];
            ws.send(JSON.stringify({
                type: 'llm',
                text: `Transitioning to ${emotion} state...`,
                emotion: emotion
            }));
            i++;
        } else {
            clearInterval(interval);
        }
    }, 10000);

    ws.on('close', () => {
        console.log('Client disconnected');
        clearInterval(interval);
    });
});

server.listen(port, () => {
    console.log(`WebSocket server is listening on ws://localhost:${port}`);
});
