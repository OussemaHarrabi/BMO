
'use client';

import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { 
  sendChatQuery, 
  ChatResponse, 
  ScreenshotRef,
  getChatSession,
  addMessageToSession,
  ChatSessionMessage
} from '../services/api';

const CATEGORIES = [
  'work', 'code', 'research', 'studying', 'meetings', 
  'entertainment', 'shopping', 'health', 'travel', 
  'finance', 'social', 'creative', 'personal'
];

interface Message {
  id: string;
  sender: 'user' | 'bmo';
  text: string;
  confidence?: number;
  processingTime?: number;
  sources?: string[];
  screenshots?: ScreenshotRef[];
  timestamp: Date;
}

interface ChatViewProps {
  sessionId?: string | null;
  onSessionUpdate?: () => void;
  onFirstMessage?: (firstMessageText: string) => void;
}

const CATEGORY_COLORS: Record<string, string> = {
  work: '#4A90A4',
  code: '#2F4F4F',
  research: '#6B8E23',
  studying: '#FF8C00',
  meetings: '#8B008B',
  entertainment: '#FF1493',
  shopping: '#FFD700',
  health: '#00FA9A',
  travel: '#1E90FF',
  finance: '#228B22',
  social: '#FF69B4',
  creative: '#9370DB',
  personal: '#A0522D',
  default: '#557A84',
};

const ChatView: React.FC<ChatViewProps> = ({ sessionId, onSessionUpdate, onFirstMessage }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [showCategories, setShowCategories] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const lastLoadedSessionRef = useRef<string | null>(null);
  
  // Viewer state
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);

  // Load session messages when sessionId changes
  useEffect(() => {
    const loadSession = async () => {
      // Skip if same session already loaded
      if (sessionId === lastLoadedSessionRef.current) return;
      
      if (!sessionId) {
        // New chat - clear messages
        setMessages([]);
        lastLoadedSessionRef.current = null;
        return;
      }

      setIsLoadingSession(true);
      try {
        const session = await getChatSession(sessionId);
        if (session && session.messages) {
          const loadedMessages: Message[] = session.messages.map((msg: ChatSessionMessage) => ({
            id: msg.id,
            sender: msg.sender,
            text: msg.text,
            confidence: msg.confidence,
            processingTime: msg.processing_time_ms,
            screenshots: msg.screenshots,
            timestamp: new Date(msg.timestamp),
          }));
          setMessages(loadedMessages);
          lastLoadedSessionRef.current = sessionId;
        }
      } catch (error) {
        console.error('Failed to load session:', error);
      } finally {
        setIsLoadingSession(false);
      }
    };

    loadSession();
  }, [sessionId]);

  const allScreenshots = useMemo(() => {
    return messages.flatMap(m => m.screenshots || []);
  }, [messages]);

  const getGlobalScreenshotIndex = (msgIndex: number, sIndex: number) => {
    let count = 0;
    for (let i = 0; i < msgIndex; i++) {
      count += (messages[i].screenshots?.length || 0);
    }
    return count + sIndex;
  };

  const handleScreenshotClick = (idx: number) => {
    setViewerIndex(idx);
  };

  const closeViewer = () => setViewerIndex(null);

  const navigateViewer = (direction: 'next' | 'prev') => {
    if (viewerIndex === null) return;
    if (direction === 'next') {
      setViewerIndex((prev) => (prev! + 1) % allScreenshots.length);
    } else {
      setViewerIndex((prev) => (prev! - 1 + allScreenshots.length) % allScreenshots.length);
    }
  };

  const handleNewDiscussion = useCallback(() => {
    if (window.confirm('Start a new discussion? This will clear current messages.')) {
      setMessages([]);
      setViewerIndex(null);
      lastLoadedSessionRef.current = null;
    }
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (viewerIndex === null) return;
      if (e.key === 'Escape') closeViewer();
      if (e.key === 'ArrowRight') navigateViewer('next');
      if (e.key === 'ArrowLeft') navigateViewer('prev');
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [viewerIndex, allScreenshots.length]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const toggleCategory = (category: string) => {
    setSelectedCategories(prev => 
      prev.includes(category) 
        ? prev.filter(c => c !== category)
        : [...prev, category]
    );
  };

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      sender: 'user',
      text: input,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    const messageText = input;
    setInput('');
    setIsLoading(true);

    const isFirstMessage = messages.length === 0;

    if (sessionId) {
      addMessageToSession(sessionId, 'user', messageText).catch(console.error);
    }

    if (isFirstMessage && onFirstMessage) {
      onFirstMessage(messageText);
    }

    try {
      const response = await sendChatQuery(messageText, selectedCategories);
      const bmoMessage: Message = {
        id: (Date.now() + 1).toString(),
        sender: 'bmo',
        text: response.answer,
        confidence: response.confidence,
        processingTime: response.processing_time_ms,
        sources: response.sources,
        screenshots: response.screenshots,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, bmoMessage]);

      if (sessionId) {
        addMessageToSession(
          sessionId, 
          'bmo', 
          response.answer, 
          response.confidence,
          response.processing_time_ms,
          response.screenshots
        ).then(() => {
          onSessionUpdate?.();
        }).catch(console.error);
      }
    } catch (error) {
      console.error('Failed to send message:', error);
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        sender: 'bmo',
        text: "Oh no! My circuits are tangled. I couldn't reach my memory banks.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);

      if (sessionId) {
        addMessageToSession(sessionId, 'bmo', errorMessage.text).catch(console.error);
      }
    } finally {
      setIsLoading(false);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Styles
  const styles = {
    container: {
      flex: 1,
      display: 'flex',
      flexDirection: 'column' as const,
      height: '100%',
      position: 'relative' as const,
    },
    screenContainer: {
      flex: 1,
      backgroundColor: '#D6F8D6',
      borderRadius: '10px',
      padding: '40px 12px 12px 12px',
      overflowY: 'auto' as const,
      marginBottom: '10px',
      boxShadow: 'inset 0 0 10px rgba(0,0,0,0.1)',
      border: '2px solid #4A90A4',
      display: 'flex',
      flexDirection: 'column' as const,
      position: 'relative' as const,
    },
    messageList: {
      display: 'flex',
      flexDirection: 'column' as const,
      gap: '12px',
    },
    message: (sender: 'user' | 'bmo') => ({
      alignSelf: sender === 'user' ? 'flex-end' : 'flex-start',
      backgroundColor: sender === 'user' ? '#fff' : 'transparent',
      color: '#2F4F4F',
      padding: '10px 15px',
      borderRadius: sender === 'user' ? '15px 15px 0 15px' : '0 15px 15px 15px',
      maxWidth: '85%',
      wordBreak: 'break-word' as const,
      boxShadow: sender === 'user' ? '0 2px 5px rgba(0,0,0,0.05)' : 'none',
      border: sender === 'user' ? 'none' : '2px dashed #4A90A4',
      fontSize: '1rem',
      lineHeight: '1.4',
      fontWeight: '600', // Bolder font
    }),
    controls: {
      display: 'flex',
      gap: '10px',
      alignItems: 'center',
    },
    input: {
      flex: 1,
      padding: '12px 15px',
      borderRadius: '25px',
      border: 'none',
      backgroundColor: '#355E68', // Darker teal for input
      color: '#fff',
      fontFamily: "'Courier New', monospace",
      fontSize: '1rem',
      fontWeight: '600',
      outline: 'none',
      boxShadow: 'inset 0 2px 5px rgba(0,0,0,0.2)',
    },
    sendButton: {
      width: '50px',
      height: '50px',
      borderRadius: '50%',
      backgroundColor: '#FF5E5E', // BMO Red Button
      border: 'none',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: 'white',
      fontWeight: 'bold',
      boxShadow: '0 4px 0 #D14545',
      transition: 'transform 0.1s',
    },
    meta: {
      fontSize: '0.7rem',
      marginTop: '4px',
      color: '#666',
      display: 'flex',
      gap: '8px',
      alignItems: 'center',
    },
    confidence: {
      backgroundColor: 'rgba(99, 197, 218, 0.2)',
      padding: '2px 6px',
      borderRadius: '4px',
    },
    loading: {
      display: 'flex',
      gap: '5px',
      padding: '10px',
      color: '#2F4F4F',
    },
    categoryPanel: {
      display: showCategories ? 'flex' : 'none',
      flexWrap: 'wrap' as const,
      gap: '6px',
      padding: '8px',
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      borderRadius: '10px',
      marginBottom: '8px',
      border: '2px dashed #4A90A4',
      maxHeight: '100px',
      overflowY: 'auto' as const,
      transition: 'all 0.3s ease',
      position: 'absolute' as const,
      top: '40px',
      left: '10px',
      right: '10px',
      zIndex: 100,
    },
    categoryChip: (selected: boolean, color: string) => ({
      padding: '6px 12px',
      borderRadius: '20px',
      fontSize: '0.8rem',
      cursor: 'pointer',
      border: `2px solid ${selected ? color : '#4A90A4'}`,
      backgroundColor: selected ? color : 'transparent',
      color: selected ? '#fff' : '#2F4F4F',
      fontWeight: 'bold',
      transition: 'all 0.2s',
      display: 'flex',
      alignItems: 'center',
      gap: '4px',
    }),
    filterToggle: {
      position: 'absolute' as const,
      top: '5px',
      right: '10px',
      zIndex: 10,
      backgroundColor: showCategories ? '#4A90A4' : '#D6F8D6',
      color: showCategories ? '#fff' : '#2F4F4F',
      border: '2px solid #4A90A4',
      borderRadius: '12px',
      padding: '4px 12px',
      fontSize: '0.75rem',
      cursor: 'pointer',
      fontWeight: 'bold',
      transition: 'all 0.2s',
      display: 'flex',
      alignItems: 'center',
      gap: '4px',
    },
    newDiscussionBtn: {
      position: 'absolute' as const,
      top: '5px',
      left: '10px',
      backgroundColor: '#FF5E5E',
      color: 'white',
      border: '2px solid #D14545',
      borderRadius: '12px',
      padding: '4px 12px',
      fontSize: '0.75rem',
      fontWeight: 'bold',
      cursor: 'pointer',
      zIndex: 10,
      boxShadow: '0 2px 0 rgba(0,0,0,0.2)',
      display: 'flex',
      alignItems: 'center',
      gap: '4px',
    },
    viewerOverlay: {
      position: 'fixed' as const,
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.95)',
      zIndex: 9999,
      display: 'flex',
      flexDirection: 'column' as const,
      alignItems: 'center',
      justifyContent: 'center',
      backdropFilter: 'blur(5px)',
    },
    viewerContent: {
      position: 'relative' as const,
      maxWidth: '100%',
      maxHeight: '100%',
      display: 'flex',
      flexDirection: 'column' as const,
      alignItems: 'center',
    },
    viewerImage: {
      maxWidth: '90vw',
      maxHeight: '80vh',
      objectFit: 'contain' as const,
      borderRadius: '8px',
      boxShadow: '0 0 50px rgba(74, 144, 164, 0.3)',
      border: '2px solid #4A90A4',
    },
    viewerControls: {
      display: 'flex',
      alignItems: 'center',
      gap: '20px',
      marginTop: '20px',
      color: '#D6F8D6',
      fontFamily: "'Courier New', monospace",
      fontSize: '1.2rem',
      fontWeight: 'bold',
    },
    viewerBtn: {
      background: 'rgba(74, 144, 164, 0.3)',
      border: '2px solid #4A90A4',
      color: '#D6F8D6',
      width: '50px',
      height: '50px',
      borderRadius: '50%',
      cursor: 'pointer',
      fontSize: '1.5rem',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      transition: 'all 0.2s',
    },
    closeBtn: {
      position: 'absolute' as const,
      top: '20px',
      right: '20px',
      background: 'transparent',
      border: 'none',
      color: '#FF5E5E',
      fontSize: '3rem',
      cursor: 'pointer',
      zIndex: 10001,
    },
    dot: {
      width: '8px',
      height: '8px',
      backgroundColor: '#2F4F4F',
      borderRadius: '50%',
      animation: 'bounce 1.4s infinite ease-in-out both',
    },
  };

  return (
    <div style={styles.container}>
      <button 
        onClick={() => setShowCategories(!showCategories)} 
        style={styles.filterToggle}
      >
        {showCategories ? '▼' : '▲'} Filters {selectedCategories.length > 0 && `(${selectedCategories.length})`}
      </button>

      {!sessionId && (
        <button 
          onClick={handleNewDiscussion} 
          style={styles.newDiscussionBtn}
          title="Clear conversation"
        >
          <span>🗑️</span> New Chat
        </button>
      )}

      <div style={styles.screenContainer}>
        <div style={styles.messageList}>
          {isLoadingSession ? (
            <div style={{ textAlign: 'center', marginTop: '40px', color: '#557A84' }}>
              <p>Loading conversation...</p>
            </div>
          ) : messages.length === 0 ? (
            <div style={{ textAlign: 'center', marginTop: '40px', color: '#557A84' }}>
              <p>Hi! I'm BMO.</p>
              <p>Ask me anything about your memories!</p>
            </div>
          ) : null}
          
          {messages.map((msg, msgIdx) => (
            <div key={msg.id} style={{ display: 'flex', flexDirection: 'column', alignItems: msg.sender === 'user' ? 'flex-end' : 'flex-start' }}>
              <div style={styles.message(msg.sender)}>
                {msg.text}
              </div>
              {msg.sender === 'bmo' && msg.screenshots && msg.screenshots.length > 0 && (
                <div style={{ 
                  display: 'flex', 
                  flexWrap: 'wrap', 
                  gap: '8px', 
                  marginTop: '8px',
                  maxWidth: '100%'
                }}>
                  {msg.screenshots.map((screenshot, idx) => (
                    <div 
                      key={idx} 
                      onClick={() => handleScreenshotClick(getGlobalScreenshotIndex(msgIdx, idx))}
                      style={{ 
                        position: 'relative',
                        borderRadius: '8px',
                        overflow: 'hidden',
                        border: '2px solid #4A90A4',
                        maxWidth: '180px',
                        flex: '1 1 auto',
                        cursor: 'pointer',
                        transition: 'transform 0.2s',
                      }}
                      onMouseEnter={(e) => e.currentTarget.style.transform = 'scale(1.02)'}
                      onMouseLeave={(e) => e.currentTarget.style.transform = 'scale(1)'}
                    >
                      <img 
                        src={`data:image/png;base64,${screenshot.image_base64}`}
                        alt={`Screenshot ${idx + 1}`}
                        style={{ 
                          width: '100%', 
                          height: 'auto',
                          display: 'block'
                        }}
                      />
                      {screenshot.source_url && (
                        <div style={{
                          position: 'absolute',
                          bottom: 0,
                          left: 0,
                          right: 0,
                          backgroundColor: 'rgba(0,0,0,0.6)',
                          color: '#fff',
                          fontSize: '0.6rem',
                          padding: '2px 4px',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis'
                        }}>
                          {screenshot.source_url}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {msg.sender === 'bmo' && (msg.confidence || msg.processingTime) && (
                <div style={styles.meta}>
                  {msg.confidence && (
                    <span style={styles.confidence}>
                      {(msg.confidence * 100).toFixed(0)}% sure
                    </span>
                  )}
                </div>
              )}
            </div>
          ))}
          
          {isLoading && (
            <div style={{ ...styles.message('bmo'), border: 'none' }}>
              <div style={styles.loading}>
                <div style={{ ...styles.dot, animationDelay: '-0.32s' }}></div>
                <div style={{ ...styles.dot, animationDelay: '-0.16s' }}></div>
                <div style={{ ...styles.dot }}></div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {showCategories && (
        <div style={styles.categoryPanel}>
          <div 
            onClick={() => setSelectedCategories([])}
            style={styles.categoryChip(selectedCategories.length === 0, '#557A84')}
          >
            All
          </div>
          {CATEGORIES.map(cat => (
            <div
              key={cat}
              onClick={() => toggleCategory(cat)}
              style={styles.categoryChip(selectedCategories.includes(cat), CATEGORY_COLORS[cat] || CATEGORY_COLORS.default)}
            >
              {cat}
            </div>
          ))}
        </div>
      )}

      <div style={styles.controls}>
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyPress}
          placeholder="Type a message..."
          style={styles.input}
          disabled={isLoading}
        />
        <button 
          onClick={handleSend} 
          style={styles.sendButton}
          disabled={isLoading}
          onMouseDown={(e) => e.currentTarget.style.transform = 'translateY(4px)'}
          onMouseUp={(e) => e.currentTarget.style.transform = 'translateY(0)'}
          onMouseLeave={(e) => e.currentTarget.style.transform = 'translateY(0)'}
        >
          GO
        </button>
      </div>

      {/* Fullscreen Viewer */}
      {viewerIndex !== null && allScreenshots[viewerIndex] && (
        <div 
          style={styles.viewerOverlay} 
          onClick={closeViewer}
        >
          <button 
            style={styles.closeBtn} 
            onClick={(e) => { e.stopPropagation(); closeViewer(); }}
          >
            &times;
          </button>
          
          <div 
            style={styles.viewerContent} 
            onClick={(e) => e.stopPropagation()}
          >
            <img 
              src={`data:image/png;base64,${allScreenshots[viewerIndex].image_base64}`}
              alt={`Screenshot ${viewerIndex + 1}`}
              style={styles.viewerImage}
            />
            
            <div style={styles.viewerControls}>
              <button 
                style={{
                  ...styles.viewerBtn, 
                  opacity: viewerIndex > 0 ? 1 : 0.3,
                  cursor: viewerIndex > 0 ? 'pointer' : 'default'
                }} 
                onClick={() => navigateViewer('prev')}
                disabled={viewerIndex === 0}
              >
                ←
              </button>
              
              <span style={{ minWidth: '80px', textAlign: 'center' }}>
                {viewerIndex + 1} / {allScreenshots.length}
              </span>
              
              <button 
                style={{
                  ...styles.viewerBtn, 
                  opacity: viewerIndex < allScreenshots.length - 1 ? 1 : 0.3,
                  cursor: viewerIndex < allScreenshots.length - 1 ? 'pointer' : 'default'
                }} 
                onClick={() => navigateViewer('next')}
                disabled={viewerIndex === allScreenshots.length - 1}
              >
                →
              </button>
            </div>
          </div>
        </div>
      )}

      <style dangerouslySetInnerHTML={{__html: `
        @keyframes bounce {
          0%, 80%, 100% { transform: scale(0); }
          40% { transform: scale(1); }
        }
      `}} />
    </div>
  );
};

export default ChatView;
