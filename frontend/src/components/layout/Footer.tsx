import Link from "next/link";

export function Footer() {
  return (
    <footer className="bg-gray-900 text-white/80 py-12 px-6">
      <div className="max-w-5xl mx-auto">
        {/* Logo */}
        <div className="mb-8">
          <span className="text-xl font-bold text-white">My App</span>
        </div>

        {/* Copyright */}
        <div className="pt-6 border-t border-white/10">
          <p className="text-[12px] text-white/30">
            &copy; {new Date().getFullYear()} My App. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}
