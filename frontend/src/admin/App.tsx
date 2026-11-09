// The admin app's screens. Every address loads the same index.html from
// FastAPI; React Router picks the screen here. Logged-in screens go inside
// <RequireSession> (or <RequireSession bare> for a screen the customer
// uses).
import { Navigate, Route, Routes } from "react-router";
import { ActivityLog } from "./pages/ActivityLog";
import { CustomerPage } from "./pages/CustomerPage";
import { Customers } from "./pages/Customers";
import { FillInHealthForm } from "./pages/FillInHealthForm";
import { Home } from "./pages/Home";
import { LockScreen } from "./pages/LockScreen";
import { NewCustomer } from "./pages/NewCustomer";
import { Prices } from "./pages/Prices";
import { Settings } from "./pages/Settings";
import { Setup } from "./pages/Setup";
import { Staff } from "./pages/Staff";
import { RequireSession } from "./session";

export function App() {
  return (
    <Routes>
      <Route path="/setup" element={<Setup />} />
      <Route path="/login" element={<LockScreen />} />
      <Route element={<RequireSession />}>
        <Route index element={<Home />} />
        <Route path="/customers" element={<Customers />} />
        <Route path="/customers/new" element={<NewCustomer />} />
        <Route path="/customers/:id" element={<CustomerPage />} />
        <Route path="/prices" element={<Prices />} />
        <Route path="/staff" element={<Staff />} />
        <Route path="/activity-log" element={<ActivityLog />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      {/* Screens the customer uses at the desk: no staff header. */}
      <Route element={<RequireSession bare />}>
        <Route
          path="/customers/:id/health-form"
          element={<FillInHealthForm />}
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
