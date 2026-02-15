'use client';

import React, { useState, useEffect, useMemo } from 'react';

// --- Types ---

interface Memory {
  id: string;
  summary: string;
  text: string;
  timestamp: string;
  category: string;
  source: string;
  image_base64?: string | null;
}

interface ApiMemory {
  memory_id: string;
  raw_text: string;
  summary: string | null;
  category: string;
  source: string;
  source_url: string | null;
  created_at: string;
  image_base64: string | null;
}

type DateFilter = 'today' | 'week' | 'month' | 'all';

// --- Constants ---

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

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// --- Helper Functions ---

const getDateKey = (dateString: string): string => {
  const date = new Date(dateString);
  return date.toISOString().split('T')[0];
};

const formatDateHeader = (isoDateKey: string): string => {
  const date = new Date(isoDateKey + 'T00:00:00');
  return date.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
};

const formatTime = (dateString: string): string => {
  const date = new Date(dateString);
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
  });
};

const getCategoryColor = (category: string): string => {
  const normalized = category.toLowerCase();
  return CATEGORY_COLORS[normalized] || CATEGORY_COLORS.default;
};

// --- Component ---

const Timeline: React.FC = () => {
  // State
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  
  // Filters
  const [dateFilter, setDateFilter] = useState<DateFilter>('all');
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);

  // Derived State: Available Categories
  const availableCategories = useMemo(() => {
    const cats = new Set(memories.map(m => m.category));
    return Array.from(cats).sort();
  }, [memories]);

  // Fetch Data
  useEffect(() => {
    const fetchMemories = async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        const now = new Date();
        
        let startDate: Date | null = null;
        
        if (dateFilter === 'today') {
          startDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        } else if (dateFilter === 'week') {
          const firstDay = now.getDate() - now.getDay();
          startDate = new Date(now.getFullYear(), now.getMonth(), firstDay);
        } else if (dateFilter === 'month') {
          startDate = new Date(now.getFullYear(), now.getMonth(), 1);
        }

        if (startDate) {
          params.append('start_date', startDate.toISOString());
        }
        params.append('limit', '100');
        
        const response = await fetch(`${API_BASE_URL}/api/memory/?${params.toString()}`);
        if (!response.ok) {
          throw new Error('Failed to fetch memories');
        }
        const data: ApiMemory[] = await response.json();
        
        const transformedMemories: Memory[] = data.map((item) => {
          const rawTextPreview = item.raw_text?.substring(0, 100) || '';
          return {
            id: item.memory_id,
            summary: item.summary || (rawTextPreview + (item.raw_text?.length > 100 ? '...' : '')),
            text: item.raw_text || '',
            timestamp: item.created_at,
            category: item.category || 'uncategorized',
            source: item.source || 'Unknown',
            image_base64: item.image_base64,
          };
        });
        
        setMemories(transformedMemories);
      } catch (err) {
        console.error('Error fetching memories:', err);
        setError('Failed to load memories');
        setMemories([]);
      } finally {
        setLoading(false);
      }
    };

    fetchMemories();
  }, [dateFilter]);

  // Filter Memories Client-Side (Categories)
  const filteredMemories = useMemo(() => {
    if (selectedCategories.length === 0) return memories;
    return memories.filter(m => selectedCategories.includes(m.category));
  }, [memories, selectedCategories]);

  // Group by Date
  const groupedMemories = useMemo(() => {
    const groups: Record<string, Memory[]> = {};
    filteredMemories.forEach(memory => {
      const dateKey = getDateKey(memory.timestamp);
      if (!groups[dateKey]) {
        groups[dateKey] = [];
      }
      groups[dateKey].push(memory);
    });
    return groups;
  }, [filteredMemories]);

  const sortedDates = Object.keys(groupedMemories).sort((a, b) => {
    return b.localeCompare(a);
  });

  // Handlers
  const toggleCategory = (cat: string) => {
    setSelectedCategories(prev => 
      prev.includes(cat) ? prev.filter(c => c !== cat) : [...prev, cat]
    );
  };

  const toggleExpand = (id: string) => {
    setExpandedId(prev => prev === id ? null : id);
  };

  // Styles
  const styles = {
    container: {
      display: 'flex',
      flexDirection: 'column' as const,
      width: '100%',
      height: '100%',
      backgroundColor: 'transparent',
      fontFamily: "'Courier New', monospace",
      fontWeight: '600', // Base font weight
      position: 'relative' as const,
    },
    header: {
      marginBottom: '15px',
      display: 'flex',
      flexDirection: 'column' as const,
      gap: '10px',
    },
    title: {
      fontSize: '1.2rem',
      color: '#2F4F4F',
      fontWeight: '800', // Heading
      textAlign: 'center' as const,
      textTransform: 'uppercase' as const,
      letterSpacing: '2px',
    },
    filterBar: {
      display: 'flex',
      gap: '8px',
      justifyContent: 'center',
      flexWrap: 'wrap' as const,
    },
    filterBtn: (active: boolean) => ({
      padding: '6px 12px',
      borderRadius: '20px',
      border: '2px solid #2F4F4F',
      backgroundColor: active ? '#2F4F4F' : 'transparent',
      color: active ? '#D6F8D6' : '#2F4F4F',
      cursor: 'pointer',
      fontSize: '0.8rem',
      fontFamily: 'inherit',
      fontWeight: '700',
      transition: 'all 0.2s',
    }),
    categoryBar: {
      display: 'flex',
      gap: '6px',
      overflowX: 'auto' as const,
      padding: '4px 0',
      scrollbarWidth: 'none' as const, // Firefox
      msOverflowStyle: 'none' as const, // IE/Edge
    },
    categoryPill: (cat: string, active: boolean) => ({
      padding: '4px 10px',
      borderRadius: '12px',
      border: `2px solid ${getCategoryColor(cat)}`,
      backgroundColor: active ? getCategoryColor(cat) : 'transparent',
      color: active ? '#fff' : getCategoryColor(cat),
      cursor: 'pointer',
      fontSize: '0.75rem',
      fontFamily: 'inherit',
      whiteSpace: 'nowrap' as const,
      transition: 'all 0.2s',
      opacity: active || selectedCategories.length === 0 ? 1 : 0.6,
    }),
    screenContainer: {
      flex: 1,
      backgroundColor: '#D6F8D6', // BMO Screen Green
      borderRadius: '15px',
      padding: '20px',
      overflowY: 'auto' as const,
      boxShadow: 'inset 0 0 10px rgba(0,0,0,0.1)',
      border: '3px solid #4A90A4',
      display: 'flex',
      flexDirection: 'column' as const,
      gap: '20px',
    },
    dateGroup: {
      display: 'flex',
      flexDirection: 'column' as const,
      gap: '10px',
    },
    dateHeader: {
      fontSize: '0.9rem',
      color: '#4A90A4',
      borderBottom: '1px dashed #4A90A4',
      paddingBottom: '4px',
      marginBottom: '8px',
      fontWeight: '800', // Heading
    },
    memoryCard: (cat: string) => ({
      backgroundColor: '#fff',
      borderRadius: '10px',
      borderLeft: `6px solid ${getCategoryColor(cat)}`,
      padding: '12px',
      cursor: 'pointer',
      transition: 'transform 0.1s, box-shadow 0.1s',
      boxShadow: '0 2px 5px rgba(0,0,0,0.05)',
      position: 'relative' as const,
      overflow: 'hidden' as const,
    }),
    cardHeader: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'flex-start',
      marginBottom: '6px',
    },
    timestamp: {
      fontSize: '0.7rem',
      color: '#888',
      marginLeft: '10px',
      flexShrink: 0,
      fontWeight: '600',
    },
    summary: {
      fontSize: '0.95rem',
      color: '#2F4F4F',
      fontWeight: '800', // Heading
      lineHeight: '1.3',
    },
    details: {
      fontSize: '0.85rem',
      color: '#555',
      marginTop: '10px',
      paddingTop: '10px',
      borderTop: '1px solid #eee',
      lineHeight: '1.4',
      animation: 'slideDown 0.2s ease-out',
    },
    badge: (cat: string) => ({
      display: 'inline-block',
      fontSize: '0.65rem',
      padding: '2px 6px',
      borderRadius: '4px',
      backgroundColor: getCategoryColor(cat),
      color: '#fff',
      marginTop: '6px',
      marginRight: '6px',
      textTransform: 'uppercase' as const,
    }),
    source: {
      fontSize: '0.65rem',
      color: '#999',
      fontStyle: 'italic',
      display: 'inline-block',
    },
    emptyState: {
      textAlign: 'center' as const,
      color: '#557A84',
      marginTop: '40px',
      fontStyle: 'italic',
    },
    loading: {
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100%',
      color: '#2F4F4F',
    },
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div style={styles.title}>Memory Timeline</div>
        
        {/* Date Filters */}
        <div style={styles.filterBar}>
          {(['all', 'today', 'week', 'month'] as DateFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setDateFilter(f)}
              style={styles.filterBtn(dateFilter === f)}
            >
              {f.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Category Filters */}
        <div style={styles.categoryBar}>
          {Object.keys(CATEGORY_COLORS).filter(c => c !== 'default').map((cat) => (
            <div
              key={cat}
              onClick={() => toggleCategory(cat)}
              style={styles.categoryPill(cat, selectedCategories.includes(cat))}
            >
              {cat}
            </div>
          ))}
        </div>
      </div>

      <div style={styles.screenContainer}>
        {loading ? (
          <div style={styles.loading}>LOADING MEMORY BANKS...</div>
        ) : sortedDates.length === 0 ? (
          <div style={styles.emptyState}>
            NO MEMORIES FOUND FOR THIS PERIOD.<br/>BMO IS EMPTY.
          </div>
        ) : (
          sortedDates.map((dateKey) => (
            <div key={dateKey} style={styles.dateGroup}>
              <div style={styles.dateHeader}>{formatDateHeader(dateKey)}</div>
              {groupedMemories[dateKey].map((memory) => (
                <div 
                  key={memory.id} 
                  style={styles.memoryCard(memory.category)}
                  onClick={() => toggleExpand(memory.id)}
                >
                  <div style={styles.cardHeader}>
                    <div style={styles.summary}>{memory.summary}</div>
                    <div style={styles.timestamp}>{formatTime(memory.timestamp)}</div>
                  </div>
                  
                  <div>
                    <span style={styles.badge(memory.category)}>{memory.category}</span>
                    <span style={styles.source}>via {memory.source}</span>
                  </div>

                  {expandedId === memory.id && (
                    <div style={styles.details}>
                      {memory.text}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ))
        )}
      </div>

      <style dangerouslySetInnerHTML={{__html: `
        @keyframes slideDown {
          from { opacity: 0; transform: translateY(-5px); }
          to { opacity: 1; transform: translateY(0); }
        }
        /* Custom Scrollbar for Webkit */
        ::-webkit-scrollbar {
          width: 8px;
          height: 8px;
        }
        ::-webkit-scrollbar-track {
          background: rgba(0,0,0,0.05);
          border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb {
          background: #4A90A4;
          border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
          background: #2F4F4F;
        }
      `}} />
    </div>
  );
};

export default Timeline;
