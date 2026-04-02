import React, { useEffect, useState } from "react";

export interface StatCardProps {
  title: string;
  value: number;
  prefix?: string;
  suffix?: string;
  trend?: number;
  icon?: React.ReactNode;
  accentColor?: "cyan" | "purple";
}

export function StatCard({ 
  title, 
  value, 
  prefix = "", 
  suffix = "", 
  trend,
  icon,
  accentColor = "cyan"
}: StatCardProps) {
  const [displayValue, setDisplayValue] = useState(0);

  useEffect(() => {
    let start = 0;
    const end = value;
    if (start === end) return;

    const totalDuration = 1500;
    let incrementTime = Math.max(totalDuration / end, 10);
    if (end > 1000) incrementTime = 20;
    
    const step = end > 100 ? Math.ceil(end / 60) : 1;
    
    const timer = setInterval(() => {
      start += step;
      if (start >= end) {
        setDisplayValue(end);
        clearInterval(timer);
      } else {
        setDisplayValue(start);
      }
    }, incrementTime);

    return () => clearInterval(timer);
  }, [value]);

  const isCyan = accentColor === "cyan";
  const glowShadow = isCyan ? "shadow-[0_0_15px_rgba(0,240,255,0.15)]" : "shadow-[0_0_15px_rgba(138,43,226,0.15)]";
  const borderHover = isCyan ? "hover:border-primary/50" : "hover:border-accent/50";
  const textGrad = isCyan ? "from-primary to-primary-light" : "from-accent to-purple-400";
  const iconBg = isCyan ? "bg-primary/10 text-primary" : "bg-accent/10 text-accent";

  return (
    <div 
      className={`relative overflow-hidden rounded-2xl border border-white/5 bg-black/40 backdrop-blur-xl p-6 transition-all duration-300 ${glowShadow} ${borderHover} group animate-fade-in`}
    >
      <div className={`absolute -inset-0.5 bg-gradient-to-br ${textGrad} opacity-0 blur-xl transition duration-500 group-hover:opacity-10`} />
      
      <div className="relative z-10 flex flex-col h-full justify-between">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-gray-400 font-medium tracking-wide text-sm uppercase">{title}</h3>
          {icon && (
            <div className={`p-2 rounded-lg ${iconBg}`}>
              {icon}
            </div>
          )}
        </div>
        
        <div>
          <div className="flex items-baseline space-x-1">
            {prefix && <span className="text-2xl font-bold text-gray-300">{prefix}</span>}
            <span className={`text-5xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r ${textGrad}`}>
              {displayValue.toLocaleString()}
            </span>
            {suffix && <span className="text-xl font-bold text-gray-300 ml-1">{suffix}</span>}
          </div>
          
          {trend !== undefined && (
            <div className="mt-4 flex items-center text-sm">
              <span className={`flex items-center font-medium ${trend >= 0 ? 'text-green-400' : 'text-rose-400'}`}>
                {trend >= 0 ? '↑' : '↓'} {Math.abs(trend)}%
              </span>
              <span className="text-gray-500 ml-2">vs last week</span>
            </div>
          )}
        </div>
      </div>
      
      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:20px_20px] opacity-20 pointer-events-none" />
    </div>
  );
}
