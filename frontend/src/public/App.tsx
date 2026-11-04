// The customer app's routes. `/c` is the page the wall QR opens (design
// doc: "The wall QR"); any other path goes there too.
import { Navigate, Route, Routes } from "react-router";
import { CheckIn } from "./pages/CheckIn";

export function App() {
  return (
    <main>
      <Routes>
        <Route path="/c" element={<CheckIn />} />
        <Route path="*" element={<Navigate to="/c" replace />} />
      </Routes>
    </main>
  );
}
