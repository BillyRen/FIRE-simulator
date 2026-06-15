import { redirect } from "next/navigation";

// The standalone dashboard (an overview "score" page) was removed: it had no
// inputs of its own, showed a financially indefensible composite score, and
// duplicated the main simulator's charts. The route is kept as a redirect so any
// stale bookmarks/links land on the simulator instead of a 404.
export default function DashboardPage() {
  redirect("/");
}
