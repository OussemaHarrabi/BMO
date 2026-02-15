'use client';

import React, { useState, useEffect, useCallback } from 'react';
import ChatView from './ChatView';
import Dashboard from './Dashboard';
import Timeline from './Timeline';
import { 
  listChatSessions, 
  createChatSession, 
  deleteChatSession,
  ChatSessionSummary 
} from '../services/api';

type View = 'chat' | 'dashboard' | 'timeline';

const BMOInterface: React.FC = () => {
  const [currentView, setCurrentView] = useState<View>('chat');
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);

  const loadSessions = useCallback(async () => {
    setIsLoadingSessions(true);
    try {
      const data = await listChatSessions(50);
      setSessions(data);
    } catch (error) {
      console.error('Failed to load sessions:', error);
    } finally {
      setIsLoadingSessions(false);
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const handleNewChat = async () => {
    const session = await createChatSession();
    if (session) {
      setCurrentSessionId(session.session_id);
      await loadSessions();
    }
  };

  const handleSelectSession = (sessionId: string) => {
    setCurrentSessionId(sessionId);
    setShowHistory(false);
  };

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (window.confirm('Delete this conversation?')) {
      const success = await deleteChatSession(sessionId);
      if (success) {
        if (currentSessionId === sessionId) {
          setCurrentSessionId(null);
        }
        await loadSessions();
      }
    }
  };

  const handleFirstMessage = async (firstMessageText: string): Promise<string | null> => {
    if (!currentSessionId) {
      const session = await createChatSession(firstMessageText.slice(0, 50));
      if (session) {
        setCurrentSessionId(session.session_id);
        await loadSessions();
        return session.session_id;
      }
    }
    return currentSessionId;
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const styles = {
    container: {
      display: 'flex',
      flexDirection: 'column' as const,
      width: '100%',
      maxWidth: '1400px',
      height: '95vh',
      margin: '0 auto',
      backgroundColor: '#63C5DA',
      borderRadius: '20px',
      padding: '12px',
      boxShadow: '0 20px 50px rgba(0,0,0,0.3), inset -3px -3px 8px rgba(0,0,0,0.1)',
      fontFamily: "'Courier New', monospace",
      fontWeight: '600',
      position: 'relative' as const,
      border: '2px solid #4A90A4',
    },
    header: {
      textAlign: 'center' as const,
      marginBottom: '8px',
    },
    headerTitle: {
      fontSize: '2.2rem',
      fontWeight: '800',
      color: '#2F4F4F',
      textShadow: '2px 2px 0px #D6F8D6',
      margin: 0,
      lineHeight: 1,
      letterSpacing: '3px',
    },
    headerSlogan: {
      fontSize: '0.85rem',
      color: '#2F4F4F',
      fontWeight: '700',
      marginTop: '3px',
      opacity: 0.9,
      letterSpacing: '1px',
    },
    face: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: '8px',
      padding: '0 10px',
      height: '25px',
    },
    eyes: {
      display: 'flex',
      gap: '40px',
      justifyContent: 'center',
      flex: 1,
    },
    eye: {
      width: '10px',
      height: '10px',
      backgroundColor: '#2F4F4F',
      borderRadius: '50%',
      animation: 'blink 4s infinite',
    },
    logo: {
      fontSize: '1rem',
      fontWeight: 'bold',
      color: '#2F4F4F',
      letterSpacing: '2px',
      writingMode: 'vertical-rl' as const,
      textOrientation: 'upright' as const,
      position: 'absolute' as const,
      right: '10px',
      top: '50%',
      transform: 'translateY(-50%)',
      opacity: 0.5,
    },
    screenWrapper: {
      flex: 1,
      display: 'flex',
      gap: '10px',
      overflow: 'hidden',
    },
    sidebar: {
      width: showHistory ? '280px' : '0px',
      backgroundColor: '#D6F8D6',
      borderRadius: '12px',
      border: showHistory ? '2px solid #4A90A4' : 'none',
      boxShadow: 'inset 0 0 15px rgba(0,0,0,0.1)',
      display: 'flex',
      flexDirection: 'column' as const,
      overflow: 'hidden',
      transition: 'width 0.3s ease',
    },
    sidebarHeader: {
      padding: '12px',
      borderBottom: '2px solid #4A90A4',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
    },
    sidebarTitle: {
      fontSize: '0.9rem',
      fontWeight: 'bold',
      color: '#2F4F4F',
    },
    newChatBtn: {
      backgroundColor: '#FF5E5E',
      color: 'white',
      border: 'none',
      borderRadius: '8px',
      padding: '6px 12px',
      fontSize: '0.75rem',
      fontWeight: 'bold',
      cursor: 'pointer',
      boxShadow: '0 2px 0 #D14545',
    },
    sessionList: {
      flex: 1,
      overflowY: 'auto' as const,
      padding: '8px',
    },
    sessionItem: (isActive: boolean) => ({
      padding: '10px',
      marginBottom: '6px',
      backgroundColor: isActive ? 'rgba(74, 144, 164, 0.2)' : 'transparent',
      borderRadius: '8px',
      cursor: 'pointer',
      border: isActive ? '2px solid #4A90A4' : '2px solid transparent',
      transition: 'all 0.2s',
    }),
    sessionTitle: {
      fontSize: '0.85rem',
      fontWeight: 'bold',
      color: '#2F4F4F',
      marginBottom: '4px',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap' as const,
    },
    sessionPreview: {
      fontSize: '0.7rem',
      color: '#557A84',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap' as const,
    },
    sessionMeta: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginTop: '4px',
      fontSize: '0.65rem',
      color: '#888',
    },
    deleteBtn: {
      backgroundColor: 'transparent',
      border: 'none',
      color: '#FF5E5E',
      cursor: 'pointer',
      fontSize: '0.9rem',
      padding: '2px 6px',
      borderRadius: '4px',
      opacity: 0.7,
    },
    historyToggle: {
      position: 'absolute' as const,
      left: '20px',
      top: '50%',
      transform: 'translateY(-50%)',
      backgroundColor: '#4A90A4',
      color: 'white',
      border: 'none',
      borderRadius: '8px',
      padding: '8px 12px',
      fontSize: '0.75rem',
      fontWeight: 'bold',
      cursor: 'pointer',
      zIndex: 10,
      boxShadow: '0 2px 5px rgba(0,0,0,0.2)',
    },
    screenBezel: {
      flex: 1,
      backgroundColor: '#D6F8D6',
      borderRadius: '12px',
      padding: '10px',
      position: 'relative' as const,
      overflow: 'hidden',
      border: '2px solid #4A90A4',
      boxShadow: 'inset 0 0 15px rgba(0,0,0,0.1)',
      display: 'flex',
      flexDirection: 'column' as const,
    },
    controlsArea: {
      marginTop: '10px',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '0 10px',
    },
    dpad: {
      width: '60px',
      height: '60px',
      position: 'relative' as const,
    },
    dpadH: {
      width: '100%',
      height: '18px',
      backgroundColor: '#FFD700',
      position: 'absolute' as const,
      top: '21px',
      left: 0,
      borderRadius: '3px',
      boxShadow: '2px 2px 0 rgba(0,0,0,0.2)',
    },
    dpadV: {
      width: '18px',
      height: '100%',
      backgroundColor: '#FFD700',
      position: 'absolute' as const,
      left: '21px',
      top: 0,
      borderRadius: '3px',
      boxShadow: '2px 2px 0 rgba(0,0,0,0.2)',
    },
    actionButtons: {
      display: 'flex',
      gap: '12px',
      alignItems: 'flex-end',
    },
    btnGroup: {
      display: 'flex',
      flexDirection: 'column' as const,
      alignItems: 'center',
      gap: '3px',
    },
    btn: (color: string, active: boolean) => ({
      width: '32px',
      height: '32px',
      borderRadius: '50%',
      backgroundColor: color,
      border: active ? '2px solid #fff' : 'none',
      boxShadow: active ? '0 0 8px rgba(255,255,255,0.8)' : '2px 3px 0 rgba(0,0,0,0.2)',
      cursor: 'pointer',
      transition: 'transform 0.1s',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#fff',
      fontSize: '0.7rem',
      fontWeight: 'bold',
      transform: active ? 'scale(1.1)' : 'scale(1)',
    }),
    btnLabel: {
      fontSize: '0.55rem',
      color: '#2F4F4F',
      fontWeight: 'bold',
      textTransform: 'uppercase' as const,
    },
    slots: {
      display: 'flex',
      gap: '8px',
      marginTop: '8px',
      justifyContent: 'center',
    },
    slot: {
      width: '50px',
      height: '6px',
      backgroundColor: '#355E68',
      borderRadius: '3px',
    }
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h1 style={styles.headerTitle}>BMO</h1>
        <div style={styles.headerSlogan}>Your Personal Memory Companion</div>
      </div>
      <div style={styles.face}>
        <div style={styles.eyes}>
          <div style={styles.eye} />
          <div style={styles.eye} />
        </div>
      </div>
      
      {currentView === 'chat' && (
        <button 
          style={styles.historyToggle}
          onClick={() => setShowHistory(!showHistory)}
        >
          {showHistory ? '◀' : '▶'} History
        </button>
      )}

      <div style={styles.screenWrapper}>
        {currentView === 'chat' && (
          <div style={styles.sidebar}>
            {showHistory && (
              <>
                <div style={styles.sidebarHeader}>
                  <span style={styles.sidebarTitle}>Chat History</span>
                  <button style={styles.newChatBtn} onClick={handleNewChat}>
                    + New
                  </button>
                </div>
                <div style={styles.sessionList}>
                  {isLoadingSessions ? (
                    <div style={{ textAlign: 'center', padding: '20px', color: '#557A84' }}>
                      Loading...
                    </div>
                  ) : sessions.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '20px', color: '#557A84', fontSize: '0.8rem' }}>
                      No conversations yet.<br />Start chatting!
                    </div>
                  ) : (
                    sessions.map((session) => (
                      <div
                        key={session.session_id}
                        style={styles.sessionItem(currentSessionId === session.session_id)}
                        onClick={() => handleSelectSession(session.session_id)}
                        onMouseEnter={(e) => {
                          if (currentSessionId !== session.session_id) {
                            e.currentTarget.style.backgroundColor = 'rgba(74, 144, 164, 0.1)';
                          }
                        }}
                        onMouseLeave={(e) => {
                          if (currentSessionId !== session.session_id) {
                            e.currentTarget.style.backgroundColor = 'transparent';
                          }
                        }}
                      >
                        <div style={styles.sessionTitle}>{session.title || 'New Chat'}</div>
                        <div style={styles.sessionPreview}>{session.preview || 'No messages'}</div>
                        <div style={styles.sessionMeta}>
                          <span>{formatDate(session.updated_at)}</span>
                          <button
                            style={styles.deleteBtn}
                            onClick={(e) => handleDeleteSession(session.session_id, e)}
                            onMouseEnter={(e) => { e.currentTarget.style.opacity = '1'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.opacity = '0.7'; }}
                          >
                            🗑️
                          </button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </>
            )}
          </div>
        )}

        <div style={styles.screenBezel}>
          {currentView === 'chat' && (
            <ChatView 
              sessionId={currentSessionId}
              onSessionUpdate={loadSessions}
              onFirstMessage={handleFirstMessage}
            />
          )}
          {currentView === 'dashboard' && <Dashboard />}
          {currentView === 'timeline' && <Timeline />}
        </div>
      </div>

      <div style={styles.controlsArea}>
        <div style={styles.dpad}>
          <div style={styles.dpadH} />
          <div style={styles.dpadV} />
          <div style={{
            position: 'absolute', 
            width: '12px', 
            height: '12px', 
            backgroundColor: '#E6C200', 
            borderRadius: '50%',
            top: '24px',
            left: '24px',
            zIndex: 2
          }} />
        </div>

        <div style={styles.actionButtons}>
          <div style={styles.btnGroup}>
            <button 
              style={styles.btn('#FF5E5E', currentView === 'chat')}
              onClick={() => setCurrentView('chat')}
            >
              A
            </button>
            <span style={styles.btnLabel}>CHAT</span>
          </div>

          <div style={styles.btnGroup}>
            <button 
              style={styles.btn('#00FA9A', currentView === 'dashboard')}
              onClick={() => setCurrentView('dashboard')}
            >
              B
            </button>
            <span style={styles.btnLabel}>STATS</span>
          </div>

          <div style={{ ...styles.btnGroup, marginBottom: '15px' }}>
            <button 
              style={{ ...styles.btn('#1E90FF', currentView === 'timeline'), width: '24px', height: '24px', fontSize: '0.5rem' }}
              onClick={() => setCurrentView('timeline')}
            >
              Start
            </button>
          </div>
        </div>
      </div>

      <div style={styles.slots}>
        <div style={styles.slot} />
        <div style={styles.slot} />
      </div>

      <style dangerouslySetInnerHTML={{__html: `
        @keyframes blink {
          0%, 48%, 52%, 100% { height: 12px; }
          50% { height: 1px; }
        }
      `}} />
    </div>
  );
};

export default BMOInterface;