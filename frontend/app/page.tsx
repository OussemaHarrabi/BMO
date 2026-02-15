'use client';

import ChatInterface from '@/components/ChatInterface';

export default function Home() {
  return (
    <>
      <style jsx global>{`
        @keyframes gradientShift {
          0% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
        
        @keyframes floatingOrbs {
          0%, 100% { transform: translateY(0px) rotate(0deg); opacity: 0.3; }
          50% { transform: translateY(-20px) rotate(180deg); opacity: 0.6; }
        }
        
        @keyframes pulse {
          0%, 100% { transform: scale(1); opacity: 0.4; }
          50% { transform: scale(1.1); opacity: 0.7; }
        }
        
        @keyframes scanline {
          0% { top: -100%; }
          100% { top: 100%; }
        }
        
        .dynamic-bg {
          position: fixed;
          top: 0;
          left: 0;
          width: 100vw;
          height: 100vh;
          background: linear-gradient(-45deg, #0F2027, #203A43, #2C5364, #1a1a2e, #16213e, #0f3460);
          background-size: 400% 400%;
          animation: gradientShift 15s ease infinite;
          z-index: -2;
        }
        
        .orb {
          position: fixed;
          border-radius: 50%;
          filter: blur(60px);
          z-index: -1;
          animation: floatingOrbs 8s ease-in-out infinite;
        }
        
        .orb-1 {
          width: 300px;
          height: 300px;
          background: radial-gradient(circle, rgba(99, 197, 218, 0.4) 0%, transparent 70%);
          top: 10%;
          left: 10%;
          animation-delay: 0s;
        }
        
        .orb-2 {
          width: 400px;
          height: 400px;
          background: radial-gradient(circle, rgba(214, 248, 214, 0.3) 0%, transparent 70%);
          top: 60%;
          right: 10%;
          animation-delay: -2s;
        }
        
        .orb-3 {
          width: 250px;
          height: 250px;
          background: radial-gradient(circle, rgba(255, 94, 94, 0.3) 0%, transparent 70%);
          bottom: 20%;
          left: 30%;
          animation-delay: -4s;
        }
        
        .orb-4 {
          width: 200px;
          height: 200px;
          background: radial-gradient(circle, rgba(255, 215, 0, 0.25) 0%, transparent 70%);
          top: 30%;
          right: 25%;
          animation-delay: -6s;
          animation: pulse 6s ease-in-out infinite;
        }
        
        .grid-overlay {
          position: fixed;
          top: 0;
          left: 0;
          width: 100vw;
          height: 100vh;
          background-image: 
            linear-gradient(rgba(99, 197, 218, 0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(99, 197, 218, 0.03) 1px, transparent 1px);
          background-size: 50px 50px;
          z-index: -1;
          pointer-events: none;
        }
        
        .scanline-effect {
          position: fixed;
          top: 0;
          left: 0;
          width: 100vw;
          height: 100vh;
          background: linear-gradient(
            to bottom,
            transparent 50%,
            rgba(99, 197, 218, 0.03) 50%
          );
          background-size: 100% 4px;
          z-index: 1000;
          pointer-events: none;
          opacity: 0.5;
        }
        
        .stars {
          position: fixed;
          top: 0;
          left: 0;
          width: 100vw;
          height: 100vh;
          z-index: -1;
          pointer-events: none;
        }
        
        .star {
          position: absolute;
          width: 2px;
          height: 2px;
          background: white;
          border-radius: 50%;
          animation: pulse 3s ease-in-out infinite;
        }
      `}</style>
      
      {/* Dynamic animated background */}
      <div className="dynamic-bg" />
      
      {/* Floating orbs */}
      <div className="orb orb-1" />
      <div className="orb orb-2" />
      <div className="orb orb-3" />
      <div className="orb orb-4" />
      
      {/* Retro grid overlay */}
      <div className="grid-overlay" />
      
      {/* CRT scanline effect */}
      <div className="scanline-effect" />
      
      {/* Twinkling stars */}
      <div className="stars">
        {[...Array(30)].map((_, i) => (
          <div
            key={i}
            className="star"
            style={{
              left: `${Math.random() * 100}%`,
              top: `${Math.random() * 100}%`,
              animationDelay: `${Math.random() * 3}s`,
              opacity: Math.random() * 0.5 + 0.2,
            }}
          />
        ))}
      </div>
      
      <main style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        padding: '2rem',
        position: 'relative',
        zIndex: 1,
      }}>
        <ChatInterface />
      </main>
    </>
  );
}
