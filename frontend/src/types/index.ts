export interface NavItem {
  label: string;
  href: string;
}

export interface Feature {
  title: string;
  description: string;
  icon: React.ReactNode;
}

export interface Review {
  content: string;
  author: string;
  role: string;
  avatarUrl: string;
  rating: number;
}
