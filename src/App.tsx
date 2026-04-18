import { useEffect, useRef, useState } from 'react';
import { Camera, Terminal, Settings, Play, Square, Activity } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

type LogType = 'info' | 'error' | 'ws';

type CvEvent = {
  summary: string;
  roadDamageCount: number;
  roadDamageLabels: string[];
  updatedAt: number;
  minConfidence?: number;
  lastReportPath?: string | null;
  location?: { latitude: number; longitude: number; updated_at?: number } | null;
};

type StickyRoadDamage = {
  count: number;
  labels: string[];
  untilMs: number;
};

const ROAD_DAMAGE_STICKY_MS = 3000;

export default function App() {
  const [activeTab, setActiveTab] = useState<'monitor' | 'logs' | 'config'>('monitor');
  const [deviceIp, setDeviceIp] = useState('100.98.6.68');
  const [isStreaming, setIsStreaming] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [logs, setLogs] = useState<{ id: number, text: string, type: LogType }[]>([]);
  const [stickyRoadDamage, setStickyRoadDamage] = useState<StickyRoadDamage | null>(null);
  const [minConfidence, setMinConfidence] = useState(0.35);
  const wsRef = useRef<WebSocket | null>(null);
  const [cvEvent, setCvEvent] = useState<CvEvent>({
    summary: 'Waiting for CV events...',
    roadDamageCount: 0,
    roadDamageLabels: [],
    updatedAt: 0,
    lastReportPath: null,
    location: null,
  });

  const addLog = (text: string, type: LogType = 'info') => {
    setLogs((prev: { id: number; text: string; type: LogType }[]) =>
      [{ id: Date.now(), text, type }, ...prev].slice(0, 50)
    );
  };

  useEffect(() => {
    addLog('Control Center Initialized', 'info');
  }, []);

  useEffect(() => {
    const wsProto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${wsProto}://${window.location.hostname}:8765`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsConnected(true);
      addLog(`Backend WebSocket connected: ${wsUrl}`, 'ws');
      addLog('Browser GPS disabled: waiting for Android phone location', 'ws');
    };

    ws.onerror = () => {
      setWsConnected(false);
      addLog('Backend WebSocket error', 'error');
    };

    ws.onclose = () => {
      setWsConnected(false);
      addLog('Backend WebSocket disconnected', 'error');
    };

    ws.onmessage = (event) => {
      if (typeof event.data !== 'string') {
        return;
      }

      try {
        const payload = JSON.parse(event.data);
        if (payload?.type === 'cv') {
          const next: CvEvent = {
            summary: payload.summary ?? 'No summary',
            roadDamageCount: Number(payload.roadDamageCount ?? 0),
            roadDamageLabels: Array.isArray(payload.roadDamageLabels) ? payload.roadDamageLabels : [],
            updatedAt: Number(payload.updatedAt ?? 0),
            minConfidence: Number(payload.minConfidence ?? 0.35),
            lastReportPath: payload.lastReportPath ?? null,
            location: payload.location ?? null,
          };

          setCvEvent(next);
          if (!Number.isNaN(next.minConfidence ?? NaN)) {
            setMinConfidence(Math.max(0, Math.min(1, Number(next.minConfidence))));
          }

          if (next.roadDamageCount > 0) {
            setStickyRoadDamage({
              count: next.roadDamageCount,
              labels: next.roadDamageLabels,
              untilMs: Date.now() + ROAD_DAMAGE_STICKY_MS,
            });

            addLog(
              `Road damage detected: ${next.roadDamageCount} (${next.roadDamageLabels.join(', ') || 'unknown'})`,
              'info'
            );
          }
        }
      } catch {
        // Ignore non-JSON payloads.
      }
    };

    return () => {
      wsRef.current = null;
      ws.close();
    };
  }, []);

  const applyConfidenceThreshold = () => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      addLog('Cannot apply confidence: backend WebSocket is not connected', 'error');
      return;
    }

    const bounded = Math.max(0, Math.min(1, minConfidence));
    ws.send(JSON.stringify({ type: 'cv_config', minConfidence: bounded }));
    addLog(`Applied road-damage min confidence = ${bounded.toFixed(2)}`, 'ws');
  };

  const stickyActive = stickyRoadDamage !== null && Date.now() < stickyRoadDamage.untilMs;
  const displayRoadDamageCount =
    cvEvent.roadDamageCount > 0 ? cvEvent.roadDamageCount : (stickyActive ? stickyRoadDamage.count : 0);
  const displayRoadDamageLabels =
    cvEvent.roadDamageCount > 0 ? cvEvent.roadDamageLabels : (stickyActive && stickyRoadDamage ? stickyRoadDamage.labels : []);

  return (
    <div className="min-h-screen bg-[#0D0D0D] text-white font-mono flex flex-col">
      {/* Header */}
      <header className="border-b border-[#1A1A1A] p-4 flex justify-between items-center bg-[#0D0D0D]">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-cyan-400 rounded-full animate-pulse" />
          <h1 className="text-xl font-bold tracking-widest text-cyan-400">CORE_ENGINE_V1.0</h1>
        </div>
        <div className="flex gap-4">
          <button 
            onClick={() => setActiveTab('monitor')}
            className={`flex items-center gap-2 px-3 py-1 rounded transition-colors ${activeTab === 'monitor' ? 'bg-cyan-900/30 text-cyan-400' : 'text-gray-500 hover:text-gray-300'}`}
          >
            <Camera size={18} /> MONITOR
          </button>
          <button 
            onClick={() => setActiveTab('logs')}
            className={`flex items-center gap-2 px-3 py-1 rounded transition-colors ${activeTab === 'logs' ? 'bg-cyan-900/30 text-cyan-400' : 'text-gray-500 hover:text-gray-300'}`}
          >
            <Terminal size={18} /> LOGS
          </button>
          <button 
            onClick={() => setActiveTab('config')}
            className={`flex items-center gap-2 px-3 py-1 rounded transition-colors ${activeTab === 'config' ? 'bg-cyan-900/30 text-cyan-400' : 'text-gray-500 hover:text-gray-300'}`}
          >
            <Settings size={18} /> CONFIG
          </button>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 p-6 flex flex-col gap-6">
        <AnimatePresence mode="wait">
          {activeTab === 'monitor' && (
            <motion.div 
              key="monitor"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="grid grid-cols-1 lg:grid-cols-3 gap-6"
            >
              {/* Camera Stream */}
              <div className="lg:col-span-2 flex flex-col gap-4">
                <div className="relative aspect-video bg-black rounded-lg border border-[#1A1A1A] overflow-hidden group">
                  {isStreaming ? (
                    <img 
                      src={`http://${deviceIp}:8080/stream`} 
                      alt="Camera Stream" 
                      className="w-full h-full object-contain"
                      onError={() => {
                        addLog('Camera stream failed to load', 'error');
                        setIsStreaming(false);
                      }}
                    />
                  ) : (
                    <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-700">
                      <Camera size={64} className="mb-4 opacity-20" />
                      <p className="text-sm">STREAM_OFFLINE</p>
                    </div>
                  )}
                  
                  <div className="absolute bottom-4 right-4 flex gap-2">
                    <button 
                      onClick={() => setIsStreaming(!isStreaming)}
                      className={`px-4 py-2 rounded-full font-bold flex items-center gap-2 transition-all ${isStreaming ? 'bg-red-500 hover:bg-red-600' : 'bg-cyan-500 hover:bg-cyan-600'} text-black`}
                    >
                      {isStreaming ? <><Square size={16} fill="black" /> STOP</> : <><Play size={16} fill="black" /> START STREAM</>}
                    </button>
                  </div>
                </div>

                <div className="bg-[#111111] border border-[#1A1A1A] p-4 rounded-lg">
                  <div className="flex items-center gap-2 mb-2 text-cyan-400 text-xs font-bold">
                    <Activity size={14} /> LIVE_TELEMETRY
                  </div>
                  <div className="grid grid-cols-3 gap-4">
                    <div className="p-3 bg-[#1A1A1A] rounded">
                      <p className="text-[10px] text-gray-500 uppercase">Latency</p>
                      <p className="text-xl font-bold">142ms</p>
                    </div>
                    <div className="p-3 bg-[#1A1A1A] rounded">
                      <p className="text-[10px] text-gray-500 uppercase">Framerate</p>
                      <p className="text-xl font-bold">15 FPS</p>
                    </div>
                    <div className="p-3 bg-[#1A1A1A] rounded">
                      <p className="text-[10px] text-gray-500 uppercase">Bitrate</p>
                      <p className="text-xl font-bold">2.4 Mbps</p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Quick Status */}
              <div className="flex flex-col gap-4">
                <div className="bg-[#111111] border border-[#1A1A1A] p-6 rounded-lg flex-1">
                  <h3 className="text-cyan-400 text-sm font-bold mb-4 tracking-tighter">ENDPOINT_IDENTIFICATION</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="text-[10px] text-gray-500 block mb-1">ANDROID_IP_ADDRESS</label>
                      <input 
                        type="text" 
                        value={deviceIp}
                        onChange={(e) => setDeviceIp(e.target.value)}
                        className="w-full bg-[#1A1A1A] border border-[#333] px-3 py-2 rounded focus:border-cyan-400 outline-none text-sm"
                      />
                    </div>
                    <div className="pt-4 border-t border-[#1A1A1A]">
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-xs text-gray-400">WebSocket Status</span>
                        <span className={`text-xs font-bold px-2 py-0.5 rounded ${wsConnected ? 'text-green-500 bg-green-500/10' : 'text-red-400 bg-red-500/10'}`}>
                          {wsConnected ? 'CONNECTED' : 'DISCONNECTED'}
                        </span>
                      </div>
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-xs text-gray-400">Camera Engine</span>
                        <span className={`text-xs ${isStreaming ? 'text-green-500' : 'text-yellow-500'} font-bold px-2 py-0.5 bg-current/10 rounded`}>{isStreaming ? 'ACTIVE' : 'IDLE'}</span>
                      </div>
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-xs text-gray-400">Road Damage</span>
                        <span className={`text-xs font-bold px-2 py-0.5 rounded ${displayRoadDamageCount > 0 ? 'text-red-400 bg-red-500/10' : 'text-green-500 bg-green-500/10'}`}>
                          {displayRoadDamageCount > 0 ? `${displayRoadDamageCount} DETECTED` : 'NONE'}
                        </span>
                      </div>
                      {displayRoadDamageCount > 0 && stickyActive && cvEvent.roadDamageCount === 0 && (
                        <div className="text-[10px] text-amber-300 mb-2">
                          Recent detection hold: {displayRoadDamageLabels.join(', ') || 'road damage'}
                        </div>
                      )}
                      <div className="mt-3 text-[11px] text-gray-300 leading-relaxed">
                        {cvEvent.summary}
                      </div>
                      {cvEvent.lastReportPath && (
                        <div className="mt-3 text-[10px] text-cyan-300 break-all">
                          Report snapshot: {cvEvent.lastReportPath}
                        </div>
                      )}
                      {cvEvent.location?.latitude != null && cvEvent.location?.longitude != null && (
                        <div className="mt-1 text-[10px] text-cyan-500">
                          GPS: {cvEvent.location.latitude.toFixed(6)}, {cvEvent.location.longitude.toFixed(6)}
                        </div>
                      )}
                      <div className="mt-1 text-[10px] text-cyan-400">
                        Min confidence: {(cvEvent.minConfidence ?? minConfidence).toFixed(2)}
                      </div>
                    </div>
                  </div>
                </div>
                
                <div className="bg-[#111111] border border-[#1A1A1A] p-4 rounded-lg h-64 overflow-hidden flex flex-col">
                  <h3 className="text-cyan-400 text-[10px] font-bold mb-2 uppercase opacity-50">Recent System Logs</h3>
                  <div className="flex-1 text-[11px] space-y-1 overflow-y-auto pr-2 custom-scrollbar">
                    {logs.map(log => (
                      <div key={log.id} className={`${log.type === 'error' ? 'text-red-400' : log.type === 'ws' ? 'text-purple-400' : 'text-gray-400'}`}>
                        <span className="opacity-30 mr-2">[{new Date(log.id).toLocaleTimeString([], { hour12: false })}]</span>
                        {log.text}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </motion.div>
          )}

          {activeTab === 'logs' && (
            <motion.div 
              key="logs"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex-1 bg-black border border-[#1A1A1A] rounded-lg p-4 font-mono text-sm overflow-hidden flex flex-col"
            >
              <div className="flex justify-between items-center mb-4 border-b border-[#1A1A1A] pb-2">
                <span className="text-cyan-400">TERMINAL_OUTPUT</span>
                <button onClick={() => setLogs([])} className="text-xs text-gray-500 hover:text-white uppercase">[Clear Logs]</button>
              </div>
              <div className="flex-1 overflow-y-auto space-y-2 pr-4 custom-scrollbar">
                {logs.map(log => (
                  <div key={log.id} className="flex gap-4 border-b border-[#111] pb-2 last:border-0">
                    <span className="text-gray-600 shrink-0">{new Date(log.id).toISOString()}</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] h-fit ${log.type === 'info' ? 'bg-blue-900/30 text-blue-400' : log.type === 'error' ? 'bg-red-900/30 text-red-400' : 'bg-purple-900/30 text-purple-400'}`}>
                      {log.type.toUpperCase()}
                    </span>
                    <span className={log.type === 'error' ? 'text-red-200' : 'text-gray-300'}>{log.text}</span>
                  </div>
                ))}
              </div>
            </motion.div>
          )}

          {activeTab === 'config' && (
            <motion.div 
              key="config"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="max-w-2xl mx-auto w-full"
            >
              <div className="bg-[#111111] border border-[#1A1A1A] rounded-lg p-8">
                <h2 className="text-2xl font-bold text-cyan-400 mb-6">SYSTEM_PARAMETERS</h2>
                <div className="space-y-6">
                  <div className="grid grid-cols-2 gap-6">
                    <div className="space-y-2">
                      <label className="text-sm text-gray-400 uppercase">WebSocket Port</label>
                      <input type="number" defaultValue="8765" className="w-full bg-[#1A1A1A] border border-[#333] p-3 rounded focus:border-cyan-400 outline-none" />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm text-gray-400 uppercase">Camera Stream Port</label>
                      <input type="number" defaultValue="8080" className="w-full bg-[#1A1A1A] border border-[#333] p-3 rounded focus:border-cyan-400 outline-none" />
                    </div>
                  </div>
                  
                  <div className="space-y-4 pt-6 border-t border-[#1A1A1A]">
                    <div className="space-y-2">
                      <label className="text-sm text-gray-400 uppercase">Road damage min confidence</label>
                      <div className="flex items-center gap-3">
                        <input
                          type="range"
                          min="0"
                          max="1"
                          step="0.05"
                          value={minConfidence}
                          onChange={(e) => setMinConfidence(Number(e.target.value))}
                          className="w-full"
                        />
                        <span className="text-cyan-300 text-sm w-12 text-right">{minConfidence.toFixed(2)}</span>
                      </div>
                      <button
                        onClick={applyConfidenceThreshold}
                        className="mt-2 px-3 py-2 rounded bg-cyan-700/30 text-cyan-300 hover:bg-cyan-600/40 text-xs uppercase tracking-wider"
                      >
                        Apply Confidence
                      </button>
                    </div>

                    <div className="flex justify-between items-center">
                      <div>
                        <p className="font-bold">Debug Mode</p>
                        <p className="text-xs text-gray-500">Enable verbose logging and telemetry</p>
                      </div>
                      <div className="w-12 h-6 bg-cyan-500 rounded-full relative cursor-pointer">
                        <div className="absolute right-1 top-1 w-4 h-4 bg-black rounded-full" />
                      </div>
                    </div>
                  </div>

                  <button className="w-full mt-8 bg-cyan-500 text-black font-bold py-4 rounded hover:bg-cyan-400 transition-colors uppercase tracking-widest">
                    Save and Apply Kernel Config
                  </button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {/* Footer Status Bar */}
      <footer className="border-t border-[#1A1A1A] p-2 px-4 flex justify-between items-center text-[10px] text-gray-500 bg-[#080808]">
        <div className="flex gap-4">
          <span>UPTIME: 04:22:11</span>
          <span>MEMORY: 142MB / 1024MB</span>
          <span>NET: STABLE</span>
        </div>
        <div className="flex gap-4 items-center">
          <span className="text-cyan-900 font-bold uppercase tracking-widest">Core Engine Pro Edition</span>
          <div className="w-2 h-2 bg-green-500 rounded-full" />
        </div>
      </footer>
    </div>
  );
}
