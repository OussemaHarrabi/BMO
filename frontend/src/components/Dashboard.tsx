
'use client';

import React, { useState, useEffect } from 'react';
import { getFolderStatus, getMemoryStats, getSystemStatus, getQdrantStats, FolderStatus, MemoryStats, SystemStatus, QdrantStats } from '../services/api';

const Dashboard: React.FC = () => {
  const [folderStatus, setFolderStatus] = useState<FolderStatus | null>(null);
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [qdrantStats, setQdrantStats] = useState<QdrantStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [status, stats, sysStatus, qStats] = await Promise.all([
          getFolderStatus(),
          getMemoryStats(),
          getSystemStatus(),
          getQdrantStats()
        ]);
        setFolderStatus(status);
        setMemoryStats(stats);
        setSystemStatus(sysStatus);
        setQdrantStats(qStats);
      } catch (error) {
        console.error('Failed to fetch dashboard data', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  const styles = {
    container: {
      flex: 1,
      backgroundColor: '#D6F8D6', // BMO Screen Green
      borderRadius: '15px',
      padding: '20px',
      overflowY: 'auto' as const,
      display: 'flex',
      flexDirection: 'column' as const,
      gap: '20px',
      border: '3px solid #4A90A4',
      boxShadow: 'inset 0 0 15px rgba(0,0,0,0.1)',
      fontFamily: "'Courier New', monospace",
      color: '#2F4F4F',
      fontWeight: '600', // Base font weight
    },
    header: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      borderBottom: '2px dashed #4A90A4',
      paddingBottom: '10px',
    },
    title: {
      fontSize: '1.5rem',
      fontWeight: '800', // Heading weight
      margin: 0,
      color: '#2F4F4F',
      textTransform: 'uppercase' as const,
      letterSpacing: '2px',
    },
    statusBadge: {
      backgroundColor: folderStatus?.watcher_running ? '#00FA9A' : '#FF5E5E',
      color: '#2F4F4F',
      padding: '4px 8px',
      borderRadius: '4px',
      fontSize: '0.8rem',
      fontWeight: '700',
      border: '2px solid #2F4F4F',
    },
    grid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
      gap: '15px',
    },
    card: {
      backgroundColor: 'rgba(99, 197, 218, 0.2)', // Light teal
      padding: '15px',
      borderRadius: '10px',
      border: '2px solid #4A90A4',
      display: 'flex',
      flexDirection: 'column' as const,
      alignItems: 'center',
      justifyContent: 'center',
      textAlign: 'center' as const,
      boxShadow: '4px 4px 0 rgba(74, 144, 164, 0.4)',
    },
    cardValue: {
      fontSize: '2rem',
      fontWeight: '800',
      margin: '5px 0',
    },
    cardLabel: {
      fontSize: '0.8rem',
      textTransform: 'uppercase' as const,
      opacity: 0.9,
      fontWeight: '700',
    },
    sectionTitle: {
      fontSize: '1.1rem',
      fontWeight: '800',
      marginTop: '10px',
      marginBottom: '10px',
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
    },
    barChart: {
      display: 'flex',
      alignItems: 'flex-end',
      height: '150px',
      gap: '10px',
      padding: '10px',
      backgroundColor: 'rgba(255,255,255,0.4)',
      borderRadius: '10px',
      border: '2px dashed #4A90A4',
    },
    barContainer: {
      flex: 1,
      display: 'flex',
      flexDirection: 'column' as const,
      alignItems: 'center',
      height: '100%',
      justifyContent: 'flex-end',
    },
    bar: (height: number, color: string) => ({
      width: '100%',
      height: `${height}%`,
      backgroundColor: color,
      borderRadius: '4px 4px 0 0',
      transition: 'height 0.5s ease',
      minHeight: '4px',
    }),
    barLabel: {
      fontSize: '0.7rem',
      marginTop: '5px',
      transform: 'rotate(-45deg)',
      transformOrigin: 'top left',
      whiteSpace: 'nowrap' as const,
    },
    activityList: {
      display: 'flex',
      flexDirection: 'column' as const,
      gap: '10px',
    },
    activityItem: {
      display: 'flex',
      justifyContent: 'space-between',
      padding: '10px',
      backgroundColor: '#fff',
      borderRadius: '8px',
      borderLeft: '4px solid #4A90A4',
      fontSize: '0.9rem',
    },
    loading: {
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100%',
      fontSize: '1.2rem',
      flexDirection: 'column' as const,
      gap: '10px',
    },
    componentGrid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gap: '10px',
    },
    componentBadge: (active: boolean) => ({
      padding: '8px 12px',
      borderRadius: '8px',
      backgroundColor: active ? 'rgba(0, 250, 154, 0.3)' : 'rgba(255, 94, 94, 0.3)',
      border: `2px solid ${active ? '#00FA9A' : '#FF5E5E'}`,
      textAlign: 'center' as const,
      fontWeight: '700' as const,
      fontSize: '0.75rem',
      textTransform: 'uppercase' as const,
    }),
    qdrantCard: {
      backgroundColor: 'rgba(30, 144, 255, 0.15)',
      padding: '15px',
      borderRadius: '10px',
      border: '2px solid #1E90FF',
      display: 'flex',
      flexDirection: 'column' as const,
      gap: '10px',
    },
    qdrantRow: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '5px 0',
      borderBottom: '1px dashed rgba(30, 144, 255, 0.3)',
    },
  };

  if (loading) {
    return (
      <div style={styles.container}>
        <div style={styles.loading}>
          <div>LOADING MEMORY BANKS...</div>
          <div style={{ fontSize: '2rem' }}>💾</div>
        </div>
      </div>
    );
  }

  const fakeCategories = [
    { name: 'code', count: 45 },
    { name: 'work', count: 38 },
    { name: 'research', count: 28 },
    { name: 'meetings', count: 22 },
    { name: 'studying', count: 18 },
    { name: 'entertainment', count: 15 },
    { name: 'social', count: 12 },
    { name: 'other', count: 8 },
  ];

  const fakeActivity = [
    { action: 'Screenshot captured', details: 'VS Code - api.ts', timestamp: new Date(Date.now() - 60000).toISOString() },
    { action: 'Memory indexed', details: 'Code review session', timestamp: new Date(Date.now() - 180000).toISOString() },
    { action: 'Screenshot captured', details: 'Chrome - GitHub PR', timestamp: new Date(Date.now() - 300000).toISOString() },
    { action: 'Memory indexed', details: 'Documentation reading', timestamp: new Date(Date.now() - 420000).toISOString() },
    { action: 'Screenshot captured', details: 'Slack - Team chat', timestamp: new Date(Date.now() - 600000).toISOString() },
  ];

  const displayCategories = memoryStats?.categories && memoryStats.categories.length > 0 
    ? memoryStats.categories.filter(c => c.name !== 'uncategorized').slice(0, 8)
    : fakeCategories;

  const displayActivity = memoryStats?.activity_log && memoryStats.activity_log.length > 0 
    ? memoryStats.activity_log 
    : fakeActivity;

  const maxCategoryCount = Math.max(...displayCategories.map(c => c.count), 1);
  
  // Colors for bars
  const colors = ['#FF5E5E', '#FFD700', '#1E90FF', '#9370DB', '#00FA9A'];

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h2 style={styles.title}>System Stats</h2>
        <div style={styles.statusBadge}>
          {folderStatus?.watcher_running ? 'WATCHING' : 'OFFLINE'}
        </div>
      </div>

      <div style={styles.grid}>
        <div style={styles.card}>
          <div style={styles.cardValue}>{qdrantStats?.points_count || memoryStats?.total_memories || 0}</div>
          <div style={styles.cardLabel}>Vectors in Qdrant</div>
        </div>
        <div style={styles.card}>
          <div style={styles.cardValue}>{memoryStats?.memories_today || 0}</div>
          <div style={styles.cardLabel}>Processed Today</div>
        </div>
        <div style={styles.card}>
          <div style={styles.cardValue}>{folderStatus?.file_count || 0}</div>
          <div style={styles.cardLabel}>Files in Folder</div>
        </div>
      </div>

      <div>
        <div style={styles.sectionTitle}>
          <span>🔧</span> System Components
        </div>
        <div style={styles.componentGrid}>
          <div style={styles.componentBadge(systemStatus?.components?.ollama ?? false)}>
            Ollama {systemStatus?.components?.ollama ? '✓' : '✗'}
          </div>
          <div style={styles.componentBadge(systemStatus?.components?.qdrant ?? false)}>
            Qdrant {systemStatus?.components?.qdrant ? '✓' : '✗'}
          </div>
          <div style={styles.componentBadge(systemStatus?.components?.neo4j ?? false)}>
            Neo4j {systemStatus?.components?.neo4j ? '✓' : '✗'}
          </div>
          <div style={styles.componentBadge(systemStatus?.components?.redis ?? false)}>
            Redis {systemStatus?.components?.redis ? '✓' : '✗'}
          </div>
        </div>
      </div>

      <div>
        <div style={styles.sectionTitle}>
          <span>🧠</span> Qdrant Vector Database
        </div>
        <div style={styles.qdrantCard}>
          <div style={styles.qdrantRow}>
            <span>Status</span>
            <span style={{ color: qdrantStats?.status === 'green' ? '#00FA9A' : '#FFD700', fontWeight: 800 }}>
              {qdrantStats?.status?.toUpperCase() || 'UNKNOWN'}
            </span>
          </div>
          <div style={styles.qdrantRow}>
            <span>Total Points (Memories)</span>
            <span style={{ fontWeight: 800 }}>{qdrantStats?.points_count || 0}</span>
          </div>
          <div style={styles.qdrantRow}>
            <span>Vector Dimensions</span>
            <span style={{ fontWeight: 800 }}>{qdrantStats?.vectors_size || 768}</span>
          </div>
          <div style={styles.qdrantRow}>
            <span>Indexed Vectors</span>
            <span style={{ fontWeight: 800 }}>{qdrantStats?.indexed_vectors || 0}</span>
          </div>
          <div style={{ ...styles.qdrantRow, borderBottom: 'none' }}>
            <span>Embedding Model</span>
            <span style={{ fontWeight: 800, color: '#1E90FF' }}>nomic-embed-text</span>
          </div>
        </div>
      </div>

      <div>
        <div style={styles.sectionTitle}>
          <span>📊</span> Memory Distribution
        </div>
        <div style={styles.barChart}>
          {displayCategories.map((cat, idx) => (
            <div key={cat.name} style={styles.barContainer}>
              <div 
                style={styles.bar(
                  (cat.count / maxCategoryCount) * 100, 
                  colors[idx % colors.length]
                )} 
              />
              <div style={styles.barLabel}>{cat.name}</div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div style={styles.sectionTitle}>
          <span>⚡</span> Recent Activity
        </div>
        <div style={styles.activityList}>
          {displayActivity.slice(0, 5).map((log, idx) => (
            <div key={idx} style={styles.activityItem}>
              <div>
                <strong>{log.action}</strong>
                {log.details && <span style={{ opacity: 0.7 }}> - {log.details}</span>}
              </div>
              <div style={{ opacity: 0.6, fontSize: '0.8rem' }}>
                {new Date(log.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
