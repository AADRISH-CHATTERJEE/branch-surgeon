"use client";

import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateReview } from "@/queries/use-reviews";

type RunReviewDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful POST /review */
  onSuccess?: () => void;
  description?: string;
};

export function RunReviewDialog({
  open,
  onOpenChange,
  onSuccess,
  description = "POST /review",
}: RunReviewDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open ? (
        <RunReviewDialogBody
          onOpenChange={onOpenChange}
          onSuccess={onSuccess}
          description={description}
        />
      ) : null}
    </Dialog>
  );
}

function RunReviewDialogBody({
  onOpenChange,
  onSuccess,
  description,
}: {
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
  description: string;
}) {
  const createReview = useCreateReview();
  const [pr, setPr] = React.useState("1");

  const submit = () => {
    const n = Number(pr);
    if (!Number.isFinite(n) || n < 1) {
      toast.error("Enter a valid PR number ≥ 1");
      return;
    }
    createReview.mutate(n, {
      onSuccess: () => {
        onOpenChange(false);
        onSuccess?.();
      },
    });
  };

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Run review</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>
      <div className="space-y-2">
        <Label htmlFor="run-review-pr">PR number</Label>
        <Input
          id="run-review-pr"
          type="number"
          min={1}
          value={pr}
          onChange={(e) => setPr(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
        />
      </div>
      <DialogFooter>
        <Button disabled={createReview.isPending} onClick={submit}>
          {createReview.isPending ? "Running…" : "Run"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
