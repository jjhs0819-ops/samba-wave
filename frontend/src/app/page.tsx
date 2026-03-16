import Link from "next/link";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";

export default function HomePage() {
  return (
    <>
      <Navbar />
      <main className="min-h-screen pt-16">
        <section className="flex flex-col items-center justify-center min-h-[80vh] px-6">
          <h1 className="text-4xl md:text-5xl font-bold text-center mb-6">
            Welcome
          </h1>
          <p className="text-lg text-muted-foreground text-center max-w-2xl mb-8">
            This is a minimal Next.js application with authentication.
          </p>
          <Link
            href="/login"
            className="inline-flex items-center justify-center px-6 py-3 text-base font-medium text-white bg-primary rounded-lg hover:bg-primary/90 transition-colors"
          >
            Get Started
          </Link>
        </section>
      </main>
      <Footer />
    </>
  );
}
