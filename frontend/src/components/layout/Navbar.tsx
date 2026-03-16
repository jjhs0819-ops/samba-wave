"use client";

import { useState, useEffect, useCallback } from "react";
import { Menu, X, LogOut } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAuth } from "@/providers/AuthProvider";

const navLinks = [
  { label: "Home", href: "/" },
];

export function Navbar() {
  const [isScrolled, setIsScrolled] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const { isAuthenticated, isLoading, logout } = useAuth();

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    let ticking = false;

    const handleScroll = () => {
      if (!ticking) {
        requestAnimationFrame(() => {
          setIsScrolled(window.scrollY > 10);
          ticking = false;
        });
        ticking = true;
      }
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const closeMobileMenu = useCallback(() => {
    setIsMobileMenuOpen(false);
  }, []);

  return (
    <nav
      className={cn(
        "fixed top-0 z-50 w-full transition-all duration-300",
        isScrolled
          ? "bg-white/98 backdrop-blur-lg shadow-sm"
          : "bg-white/95 backdrop-blur-sm"
      )}
    >
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        {/* Logo */}
        <Link href="/" className="flex items-center">
          <span className="text-xl font-bold text-primary">My App</span>
        </Link>

        {/* Desktop Navigation */}
        <div className="hidden md:flex items-center gap-8">
          {navLinks.map((link) => (
            <Link
              key={link.label}
              href={link.href}
              className="text-[15px] text-gray-700 hover:text-primary font-medium transition-colors duration-200"
            >
              {link.label}
            </Link>
          ))}
        </div>

        {/* Auth Buttons */}
        <div className="hidden md:flex items-center gap-4 min-w-[120px] justify-end">
          {mounted && !isLoading ? (
            isAuthenticated ? (
              <>
                <Link
                  href="/login"
                  className="text-[15px] text-gray-700 hover:text-primary font-medium transition-colors duration-200"
                >
                  My Account
                </Link>
                <button
                  onClick={logout}
                  className="text-gray-500 hover:text-red-500 transition-colors duration-200 p-2"
                  aria-label="Logout"
                >
                  <LogOut size={20} />
                </button>
              </>
            ) : (
              <Link href="/login">
                <Button
                  size="sm"
                  className="h-10 px-6 rounded-full text-[14px] font-semibold bg-primary hover:bg-primary/90 hover:scale-105 hover:shadow-lg transition-all duration-200"
                >
                  Login
                </Button>
              </Link>
            )
          ) : (
            <div className="w-[72px] h-10" />
          )}
        </div>

        {/* Mobile Menu Toggle */}
        <button
          className="md:hidden text-gray-900 p-2 -mr-2"
          onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          aria-label={isMobileMenuOpen ? "Close menu" : "Open menu"}
        >
          {isMobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
        </button>
      </div>

      {/* Mobile Menu */}
      <div
        className={cn(
          "md:hidden absolute top-16 left-0 w-full bg-white border-b border-gray-100 transition-all duration-300 overflow-hidden shadow-lg",
          isMobileMenuOpen ? "max-h-96 opacity-100" : "max-h-0 opacity-0"
        )}
      >
        <div className="px-6 py-5 flex flex-col gap-1">
          {navLinks.map((link) => (
            <Link
              key={link.label}
              href={link.href}
              className="text-[15px] text-gray-700 hover:text-primary font-medium py-3.5 transition-colors border-b border-gray-50 last:border-0"
              onClick={closeMobileMenu}
            >
              {link.label}
            </Link>
          ))}
          {mounted && !isLoading && (
            <div className="flex items-center justify-between pt-5 mt-3 border-t border-gray-100">
              {isAuthenticated ? (
                <>
                  <Link
                    href="/login"
                    className="text-[15px] text-gray-600 hover:text-gray-900 font-medium"
                    onClick={closeMobileMenu}
                  >
                    My Account
                  </Link>
                  <button
                    onClick={() => {
                      logout();
                      closeMobileMenu();
                    }}
                    className="text-gray-500 hover:text-red-500 transition-colors duration-200 p-2"
                    aria-label="Logout"
                  >
                    <LogOut size={20} />
                  </button>
                </>
              ) : (
                <Link href="/login" onClick={closeMobileMenu}>
                  <Button
                    size="sm"
                    className="h-10 px-6 rounded-full text-[14px] font-semibold bg-primary hover:bg-primary/90 hover:scale-105 hover:shadow-lg transition-all duration-200"
                  >
                    Login
                  </Button>
                </Link>
              )}
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}
